"""Loading, scaling, windowing and splitting of the close-price series."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


class DataError(ValueError):
    """Raised for invalid input data or parameters."""


def load_candles(path: str) -> tuple[pd.DatetimeIndex, np.ndarray]:
    """Return (timestamps, close) sorted chronologically, rows with missing values dropped."""
    try:
        df = pd.read_csv(path)
    except FileNotFoundError:
        raise DataError(f"data file not found: {path}")
    except Exception as exc:  # malformed csv
        raise DataError(f"cannot read {path}: {exc}")
    missing = [c for c in ("Date", "Close") if c not in df.columns]
    if missing:
        raise DataError(f"{path}: missing required column(s): {', '.join(missing)}")
    dates = pd.to_datetime(df["Date"], errors="coerce")
    close = pd.to_numeric(df["Close"], errors="coerce")
    ok = dates.notna() & close.notna() & np.isfinite(close.astype(float)) & ~df.isna().any(axis=1)
    dates, close = dates[ok], close[ok].astype(float)
    order = np.argsort(dates.to_numpy(), kind="stable")
    idx = pd.DatetimeIndex(dates.to_numpy()[order])
    values = close.to_numpy(dtype=np.float64)[order]
    if len(values) == 0:
        raise DataError(f"{path}: no valid rows")
    return idx, values


@dataclass(frozen=True)
class Scaler:
    """Min-max scaler to [0, 1]."""

    min: float
    max: float

    @classmethod
    def fit(cls, x: np.ndarray) -> "Scaler":
        return cls(float(np.min(x)), float(np.max(x)))

    @property
    def range(self) -> float:
        return self.max - self.min

    def transform(self, x):
        x = np.asarray(x, dtype=np.float64)
        if self.range == 0:
            return np.zeros_like(x)
        return (x - self.min) / self.range

    def inverse(self, x):
        return np.asarray(x, dtype=np.float64) * self.range + self.min


def make_windows(series: np.ndarray, input_steps: int, output_steps: int, stride: int):
    """Return X (n, input_steps, 1) and y (n, output_steps); offsets 0, stride, 2*stride, ..."""
    if input_steps < 1 or output_steps < 1 or stride < 1:
        raise DataError("input-steps, output-steps and stride must be positive integers")
    series = np.asarray(series, dtype=np.float64)
    n = (len(series) - input_steps - output_steps) // stride + 1 if len(series) >= input_steps + output_steps else 0
    if n < 1:
        raise DataError(
            f"series of length {len(series)} is too short for input_steps={input_steps} + output_steps={output_steps}"
        )
    offs = np.arange(n) * stride
    X = np.stack([series[o:o + input_steps] for o in offs])[..., None]
    y = np.stack([series[o + input_steps:o + input_steps + output_steps] for o in offs])
    return X, y


def split_chronological(X, y, train_frac: float = 0.8):
    n = len(X)
    n_train = int(np.floor(train_frac * n))
    if n_train < 1 or n - n_train < 1:
        raise DataError(f"{n} sample(s) is not enough for a non-empty train/validation split")
    return X[:n_train], y[:n_train], X[n_train:], y[n_train:]
