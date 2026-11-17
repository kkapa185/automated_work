import numpy as np
import pandas as pd
import pytest

from btcpredict_lib import data as D
from conftest import write_csv


def test_r2_load_sorts_and_drops_missing(tmp_path):
    p = tmp_path / "a.csv"
    write_csv(p, np.arange(10, dtype=float) + 1)
    df = pd.read_csv(p)
    df.loc[3, "Close"] = np.nan
    df.to_csv(p, index=False)
    dates, close = D.load_candles(str(p))
    assert len(close) == 9 and dates.is_monotonic_increasing
    assert list(close) == [1, 2, 3, 4, 5, 6, 7, 9, 10] or sorted(close) == list(close)


def test_r2_errors(tmp_path):
    with pytest.raises(D.DataError):
        D.load_candles(str(tmp_path / "nope.csv"))
    p = tmp_path / "b.csv"
    p.write_text("A,B\n1,2\n")
    with pytest.raises(D.DataError, match="missing required"):
        D.load_candles(str(p))


def test_r3_scaler_roundtrip_and_constant():
    x = np.array([5.0, 10.0, 7.5])
    s = D.Scaler.fit(x)
    assert list(s.transform(x)) == [0, 1, 0.5]
    assert np.allclose(s.inverse(s.transform(x)), x)
    c = D.Scaler.fit(np.array([3.0, 3.0]))
    assert list(c.transform([3.0, 3.0])) == [0, 0] and c.inverse(0.0) == 3.0


def test_r4_windows():
    s = np.arange(20, dtype=float)
    X, y = D.make_windows(s, 5, 2, 3)
    # offsets 0,3,6,9,12 (12+7=19<=20); 15+7>20
    assert X.shape == (5, 5, 1) and y.shape == (5, 2)
    assert list(X[2, :, 0]) == [6, 7, 8, 9, 10] and list(y[2]) == [11, 12]
    assert list(y[-1]) == [17, 18]


def test_r4_exact_fit_and_errors():
    X, y = D.make_windows(np.arange(7.0), 5, 2, 1)
    assert len(X) == 1
    with pytest.raises(D.DataError):
        D.make_windows(np.arange(6.0), 5, 2, 1)
    with pytest.raises(D.DataError):
        D.make_windows(np.arange(60.0), 5, 2, 0)


def test_r5_split_floor_chronological():
    X, y = D.make_windows(np.arange(100.0), 5, 2, 5)  # n=19
    a, b, c, d = D.split_chronological(X, y)
    assert len(a) == 15 and len(c) == 4  # floor(15.2)
    assert a[-1, 0, 0] < c[0, 0, 0]
    with pytest.raises(D.DataError):
        D.split_chronological(X[:1], y[:1])


def test_r2_drops_rows_with_any_missing_value(tmp_path):
    from conftest import write_csv
    p = tmp_path / "m.csv"
    write_csv(p, np.arange(1.0, 11.0), shuffle=False)
    df = pd.read_csv(p)
    df.loc[2, "VolumeTo"] = np.nan
    df.loc[5, "Close"] = np.nan
    df.to_csv(p, index=False)
    _, close = D.load_candles(str(p))
    assert list(close) == [1, 2, 4, 5, 7, 8, 9, 10]


def test_r13_compare_bad_metrics(tmp_path):
    from btcpredict_lib.compare import compare
    (tmp_path / "r").mkdir()
    (tmp_path / "r" / "metrics.json").write_text("{}")
    with pytest.raises(D.DataError):
        compare([str(tmp_path / "r")], str(tmp_path / "o.md"))
