"""Training / fitting and evaluation of a model; writes the run directory."""
from __future__ import annotations

import json
import os
import random

import numpy as np
import pandas as pd

from . import data as D
from . import models as M


def set_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    import keras
    import tensorflow as tf

    keras.utils.set_random_seed(seed)
    try:
        tf.config.experimental.enable_op_determinism()
    except Exception:
        pass


def _plot(path, scaler, y_true, y_pred, model_name, input_steps, stride):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(11, 4.5))
    out = y_true.shape[1]
    for i in range(len(y_true)):
        t = np.arange(out) + i * stride
        ax.plot(t, scaler.inverse(y_true[i]), color="tab:blue", lw=1.2, label="ground truth" if i == 0 else None)
        ax.plot(t, scaler.inverse(y_pred[i]), color="tab:red", lw=1.0, ls="--", label="prediction" if i == 0 else None)
    ax.set_title(f"Validation: {model_name} predictions vs ground truth")
    ax.set_xlabel("validation time step (hours, windows placed at their stride offsets)")
    ax.set_ylabel("Close (USD)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def train_run(model, data, input_steps=256, output_steps=16, stride=16, epochs=30, seed=0, out="runs/run"):
    if model not in M.ALL_MODELS:
        raise D.DataError(f"unknown model: {model}")
    if epochs < 1:
        raise D.DataError("epochs must be >= 1")
    if model == "lag" and output_steps > input_steps:
        raise D.DataError("lag baseline needs output_steps <= input_steps")
    _, close = D.load_candles(data)
    scaler = D.Scaler.fit(close)
    X, y = D.make_windows(scaler.transform(close), input_steps, output_steps, stride)
    Xtr, ytr, Xva, yva = D.split_chronological(X, y)
    set_seed(seed)
    os.makedirs(out, exist_ok=True)

    if model in M.NN_MODELS:
        import keras

        net = M.build_keras_model(model, input_steps, output_steps)
        Xtr32, ytr32 = Xtr.astype("float32"), ytr.astype("float32")
        Xva32, yva32 = Xva.astype("float32"), yva.astype("float32")
        state = {"best": np.inf, "epoch": 0, "weights": None}

        class Best(keras.callbacks.Callback):
            def on_epoch_end(self, epoch, logs=None):
                if logs["val_loss"] < state["best"]:
                    state.update(best=logs["val_loss"], epoch=epoch + 1, weights=self.model.get_weights())

        hist = net.fit(Xtr32, ytr32, validation_data=(Xva32, yva32), epochs=epochs, batch_size=8,
                       shuffle=True, verbose=0, callbacks=[Best()])
        net.set_weights(state["weights"])
        history = pd.DataFrame({"epoch": np.arange(1, epochs + 1), "loss": hist.history["loss"],
                                "val_loss": hist.history["val_loss"]})
        best_epoch = state["epoch"]
        pred = net.predict(Xva32, verbose=0).astype(np.float64)
        net.save(os.path.join(out, M.MODEL_FILES[model]))
    else:
        base = M.LagBaseline(output_steps) if model == "lag" else M.LinearBaseline()
        base.fit(Xtr, ytr)
        base.save(os.path.join(out, M.MODEL_FILES[model]))
        pred = base.predict(Xva)
        best_epoch = 0
        history = pd.DataFrame({"epoch": [0], "loss": [float(np.mean((base.predict(Xtr) - ytr) ** 2))],
                                "val_loss": [float(np.mean((pred - yva) ** 2))]})

    mse_scaled = float(np.mean((pred - yva) ** 2))
    mse_usd = float(np.mean((scaler.inverse(pred) - scaler.inverse(yva)) ** 2))
    metrics = {
        "model": model, "epochs": int(epochs), "input_steps": int(input_steps),
        "output_steps": int(output_steps), "stride": int(stride), "seed": int(seed),
        "n_train": int(len(Xtr)), "n_val": int(len(Xva)), "best_epoch": int(best_epoch),
        "val_mse_scaled": mse_scaled, "val_mse_usd": mse_usd, "val_rmse_usd": float(np.sqrt(mse_usd)),
    }
    with open(os.path.join(out, "metrics.json"), "w") as f:
        json.dump(metrics, f, indent=2)
    with open(os.path.join(out, "config.json"), "w") as f:
        json.dump({**metrics, "scaler_min": scaler.min, "scaler_max": scaler.max}, f, indent=2)
    history.to_csv(os.path.join(out, "history.csv"), index=False)
    _plot(os.path.join(out, "val_predictions.png"), scaler, yva, pred, model, input_steps, stride)
    return metrics
