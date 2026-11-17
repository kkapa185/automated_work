"""Model definitions: Keras CNN/LSTM/GRU and numpy lag/linear baselines."""
from __future__ import annotations

import json
import os

import numpy as np

from .data import DataError

NN_MODELS = ("cnn", "lstm", "gru")
BASELINES = ("lag", "linear")
ALL_MODELS = NN_MODELS + BASELINES


def cnn_second_conv(input_steps: int, output_steps: int) -> tuple[int, int]:
    """(kernel, stride) of the 2nd conv so its output length equals output_steps.

    Default config (256 -> 79 -> 16) uses the specified kernel 16 / stride 4.
    """
    l1 = (input_steps - 20) // 3 + 1
    if l1 < 1:
        raise DataError("cnn needs input_steps >= 20")
    for k, s in [(16, 4)] + [(l1 - (output_steps - 1) * s, s) for s in (4, 3, 2, 1)]:
        if k >= 1 and l1 >= k and (l1 - k) // s + 1 == output_steps:
            return k, s
    raise DataError(f"cnn cannot produce output_steps={output_steps} from input_steps={input_steps}")


def build_keras_model(name: str, input_steps: int, output_steps: int):
    import keras
    from keras import layers

    inp = layers.Input((input_steps, 1))
    if name == "cnn":
        k, s = cnn_second_conv(input_steps, output_steps)
        x = layers.Conv1D(8, 20, strides=3, activation="relu")(inp)
        x = layers.Dropout(0.5)(x)
        x = layers.Conv1D(1, k, strides=s)(x)
        out = layers.Reshape((output_steps,))(x)
    elif name == "lstm":
        x = layers.LSTM(50)(inp)
        x = layers.Activation("tanh")(x)
        x = layers.Dropout(0.2)(x)
        x = layers.Dense(output_steps)(x)
        out = layers.LeakyReLU()(x)
    elif name == "gru":
        x = layers.GRU(50)(inp)
        x = layers.Activation("tanh")(x)
        x = layers.Dropout(0.2)(x)
        x = layers.Dense(output_steps)(x)
        out = layers.ReLU()(x)
    else:
        raise DataError(f"unknown neural model: {name}")
    model = keras.Model(inp, out, name=name)
    model.compile(optimizer=keras.optimizers.Adam(), loss="mse")
    return model


class LagBaseline:
    def __init__(self, output_steps: int):
        self.output_steps = output_steps

    def fit(self, X, y):
        return self

    def predict(self, X):
        X = np.asarray(X)
        if X.shape[1] < self.output_steps:
            raise DataError("lag baseline needs output_steps <= input_steps")
        return X[:, -self.output_steps:, 0].copy()

    def save(self, path):
        with open(path, "w") as f:
            json.dump({"type": "lag", "output_steps": self.output_steps}, f)


class LinearBaseline:
    """One OLS regression (with intercept) per output step on the input window."""

    def __init__(self):
        self.coef = None  # (input_steps + 1, output_steps)

    @staticmethod
    def _design(X):
        X = np.asarray(X, dtype=np.float64)[..., 0]
        return np.hstack([X, np.ones((len(X), 1))])

    def fit(self, X, y):
        self.coef, *_ = np.linalg.lstsq(self._design(X), np.asarray(y, dtype=np.float64), rcond=None)
        return self

    def predict(self, X):
        return self._design(X) @ self.coef

    def save(self, path):
        np.savez(path, coef=self.coef)


def load_baseline(name: str, path: str):
    if name == "lag":
        with open(path) as f:
            return LagBaseline(json.load(f)["output_steps"])
    m = LinearBaseline()
    m.coef = np.load(path)["coef"]
    return m


MODEL_FILES = {"cnn": "model.keras", "lstm": "model.keras", "gru": "model.keras",
               "lag": "model.json", "linear": "model.npz"}


def load_predictor(run_dir: str, name: str):
    """Return an object with .predict(X) -> (n, output_steps) for a saved run."""
    path = os.path.join(run_dir, MODEL_FILES[name])
    if not os.path.exists(path):
        raise DataError(f"model file missing: {path}")
    if name in BASELINES:
        return load_baseline(name, path)
    import keras
    model = keras.models.load_model(path)

    class _Wrap:
        def predict(self, X):
            return model.predict(np.asarray(X, dtype=np.float32), verbose=0)

    return _Wrap()
