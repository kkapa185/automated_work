"""Run the reference project's pipeline (khuangaf/CryptocurrencyPrediction) under the benchmark protocol.

Faithful port to tf.keras 3: windowing uses the repository's own PastSampler class; model definitions,
scaling (MinMax on the whole series), 80/20 split, batch size and best-validation-epoch reporting mirror
CNN.py / LSTM.py / GRU.py / Baseline.ipynb / LinearRegression.ipynb. The only protocol change is the
sample stride (the repo's sliding_window=False uses stride = input+output on 5-minute data; with hourly
data we use a stride of 16 to obtain a comparable number of samples).
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")


def load_past_sampler(ref: Path):
    spec = importlib.util.spec_from_file_location("PastSampler", ref / "PastSampler.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.PastSampler


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reference", required=True)
    ap.add_argument("--data", required=True)
    ap.add_argument("--models", nargs="+", default=["lag", "linear", "cnn", "lstm", "gru"])
    ap.add_argument("--epochs", type=int, default=30)
    ap.add_argument("--stride", type=int, default=16)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    from sklearn.linear_model import LinearRegression
    from sklearn.preprocessing import MinMaxScaler

    df = pd.read_csv(a.data).dropna()
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.sort_values("Date").reset_index(drop=True)
    close = df["Close"].values.astype("float64").reshape(-1, 1)
    scaler = MinMaxScaler()
    scaled = scaler.fit_transform(close)
    A = scaled[:, None, :]
    PastSampler = load_past_sampler(Path(a.reference))
    B, Y = PastSampler(256, 16, sliding_window=True).transform(A)
    B, Y = B[:: a.stride], Y[:: a.stride]
    n_train = int(0.8 * B.shape[0])
    xtr, ytr = B[:n_train], Y[:n_train, :, 0]
    xva, yva = B[n_train:], Y[n_train:, :, 0]

    def usd(pred):
        p = scaler.inverse_transform(pred.reshape(-1, 1)).reshape(pred.shape)
        t = scaler.inverse_transform(yva.reshape(-1, 1)).reshape(yva.shape)
        mse = float(np.mean((p - t) ** 2))
        return {"val_mse_scaled": float(np.mean((pred - yva) ** 2)), "val_mse_usd": mse, "val_rmse_usd": mse ** 0.5}

    results = {}
    for m in a.models:
        if m == "lag":
            results[m] = usd(xva[:, -16:, 0])
        elif m == "linear":
            pred = np.zeros(yva.shape)
            for i in range(16):
                pred[:, i] = LinearRegression().fit(xtr[:, :, 0], ytr[:, i]).predict(xva[:, :, 0])
            results[m] = usd(pred)
        else:
            import keras
            from keras import layers
            keras.utils.set_random_seed(a.seed)
            model = keras.Sequential([keras.Input(shape=(256, 1))])
            if m == "cnn":
                model.add(layers.Conv1D(activation="relu", strides=3, filters=8, kernel_size=20))
                model.add(layers.Dropout(0.5))
                model.add(layers.Conv1D(strides=4, filters=1, kernel_size=16))
                ytr_m, yva_m = Y[:n_train], Y[n_train:]
            else:
                model.add(layers.LSTM(50) if m == "lstm" else layers.GRU(50))
                model.add(layers.Activation("tanh"))
                model.add(layers.Dropout(0.2))
                model.add(layers.Dense(16))
                model.add(layers.LeakyReLU() if m == "lstm" else layers.Activation("relu"))
                ytr_m, yva_m = ytr, yva
            model.compile(loss="mse", optimizer="adam")
            best = {"val_loss": float("inf")}

            class Best(keras.callbacks.Callback):
                def on_epoch_end(self, epoch, logs=None):
                    if logs["val_loss"] < best["val_loss"]:
                        pred = self.model.predict(xva, verbose=0).reshape(yva.shape)
                        best.update(val_loss=logs["val_loss"], epoch=epoch + 1, pred=pred)

            model.fit(xtr, ytr_m, batch_size=8, epochs=a.epochs, validation_data=(xva, yva_m), verbose=0,
                      callbacks=[Best()])
            results[m] = usd(best["pred"]) | {"best_epoch": best["epoch"]}
        results[m] |= {"n_train": int(n_train), "n_val": int(B.shape[0] - n_train)}
        print(m, results[m], flush=True)
    Path(a.out).write_text(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
