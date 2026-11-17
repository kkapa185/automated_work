"""Forecast the output window after the last candle of a data file."""
from __future__ import annotations

import json
import os

import numpy as np
import pandas as pd

from . import data as D
from . import models as M


def load_config(run_dir: str) -> dict:
    p = os.path.join(run_dir, "config.json")
    if not os.path.exists(p):
        raise D.DataError(f"not a run directory (config.json missing): {run_dir}")
    with open(p) as f:
        return json.load(f)


def forecast(run_dir: str, data: str, out: str) -> pd.DataFrame:
    cfg = load_config(run_dir)
    dates, close = D.load_candles(data)
    I, O = cfg["input_steps"], cfg["output_steps"]
    if len(close) < I:
        raise D.DataError(f"need at least {I} candles, got {len(close)}")
    scaler = D.Scaler(cfg["scaler_min"], cfg["scaler_max"])
    window = scaler.transform(close[-I:])[None, :, None]
    pred = M.load_predictor(run_dir, cfg["model"]).predict(window)[0]
    usd = scaler.inverse(pred)
    step = pd.Timedelta(hours=1)
    if len(dates) > 1:
        tail = dates[-10:]
        med = pd.Series(tail[1:] - tail[:-1]).median()
        if pd.notna(med) and med > pd.Timedelta(0):
            step = med
    future = [dates[-1] + step * (i + 1) for i in range(O)]
    df = pd.DataFrame({"Date": pd.DatetimeIndex(future).strftime("%Y-%m-%d %H:%M"), "Close": usd})
    df.to_csv(out, index=False)
    return df
