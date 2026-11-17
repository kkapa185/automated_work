import os
import sys

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
os.environ.setdefault("MPLBACKEND", "Agg")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
import pytest


def write_csv(path, close, shuffle=True, start="2020-01-01 00:00"):
    dates = pd.date_range(start, periods=len(close), freq="h")
    df = pd.DataFrame({"Date": dates.strftime("%Y-%m-%d %H:%M"), "Symbol": "BTCUSD", "Open": close, "High": close,
                       "Low": close, "Close": close, "VolumeFrom": 1.0, "VolumeTo": 1.0})
    if shuffle:
        df = df.iloc[::-1]  # file order is newest first, like the real data
    df.to_csv(path, index=False)


@pytest.fixture(scope="session")
def synth_csv(tmp_path_factory):
    p = tmp_path_factory.mktemp("d") / "synth.csv"
    t = np.arange(400)
    write_csv(p, 100 + 10 * np.sin(t / 15) + t * 0.05)
    return str(p)
