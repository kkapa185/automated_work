import json
import os
import subprocess
import sys

import numpy as np
import pandas as pd
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARGS = ["--input-steps", "48", "--output-steps", "8", "--stride", "8", "--epochs", "2"]


def run(*a, check=True):
    r = subprocess.run([os.path.join(ROOT, "btcpredict"), *a], capture_output=True, text=True, cwd=ROOT)
    if check:
        assert r.returncode == 0, r.stderr[-2000:]
    return r


@pytest.mark.parametrize("model", ["cnn", "lstm", "gru", "lag", "linear"])
def test_r1_r8_r9_r10_r12_end_to_end(model, synth_csv, tmp_path):
    out = tmp_path / model
    run("train", "--model", model, "--data", synth_csv, *ARGS, "--out", str(out))
    m = json.load(open(out / "metrics.json"))
    for k in ["model", "epochs", "input_steps", "output_steps", "stride", "n_train", "n_val", "best_epoch",
              "val_mse_scaled", "val_mse_usd", "val_rmse_usd"]:
        assert k in m
    assert m["model"] == model and m["n_train"] == int(0.8 * (m["n_train"] + m["n_val"]))
    # n = (400-48-8)//8+1 = 44
    assert (m["n_train"], m["n_val"]) == (35, 9)
    assert m["val_rmse_usd"] == pytest.approx(np.sqrt(m["val_mse_usd"]))
    assert os.path.getsize(out / "val_predictions.png") > 1000
    h = pd.read_csv(out / "history.csv")
    assert {"epoch", "val_loss"} <= set(h.columns)
    if model in ("cnn", "lstm", "gru"):
        assert len(h) == 2 and m["best_epoch"] == int(h.val_loss.idxmin()) + 1
        assert (out / "model.keras").exists()
        assert m["val_mse_scaled"] == pytest.approx(h.val_loss.min(), rel=1e-3)
    fc = tmp_path / "f.csv"
    run("predict", "--run", str(out), "--data", synth_csv, "--out", str(fc))
    f = pd.read_csv(fc)
    assert len(f) == 8 and list(f.columns) == ["Date", "Close"] and np.isfinite(f.Close).all()
    assert f.Date[0] == "2020-01-17 16:00"  # 400 hourly candles from 2020-01-01 00:00 end at 01-17 15:00
    assert 50 < f.Close.mean() < 200


def test_r9_usd_metrics_consistent(synth_csv, tmp_path):
    run("train", "--model", "lag", "--data", synth_csv, *ARGS, "--out", str(tmp_path / "l"))
    m = json.load(open(tmp_path / "l" / "metrics.json"))
    cfg = json.load(open(tmp_path / "l" / "config.json"))
    rng = cfg["scaler_max"] - cfg["scaler_min"]
    assert m["val_mse_usd"] == pytest.approx(m["val_mse_scaled"] * rng ** 2, rel=1e-9)


def test_r7_lag_metric_independent_check(synth_csv, tmp_path):
    from btcpredict_lib import data as D
    run("train", "--model", "lag", "--data", synth_csv, *ARGS, "--out", str(tmp_path / "l"))
    _, c = D.load_candles(synth_csv)
    s = D.Scaler.fit(c).transform(c)
    X, y = D.make_windows(s, 48, 8, 8)
    _, _, Xv, yv = D.split_chronological(X, y)
    exp = np.mean((Xv[:, -8:, 0] - yv) ** 2)
    m = json.load(open(tmp_path / "l" / "metrics.json"))
    assert m["val_mse_scaled"] == pytest.approx(exp)


def test_r11_reproducible(synth_csv, tmp_path):
    for n in "ab":
        run("train", "--model", "gru", "--data", synth_csv, *ARGS, "--seed", "3", "--out", str(tmp_path / n))
    a = json.load(open(tmp_path / "a" / "metrics.json"))
    b = json.load(open(tmp_path / "b" / "metrics.json"))
    assert a == b
    run("train", "--model", "gru", "--data", synth_csv, *ARGS, "--seed", "4", "--out", str(tmp_path / "c"))
    assert json.load(open(tmp_path / "c" / "metrics.json"))["val_mse_scaled"] != a["val_mse_scaled"]


def test_r13_compare(synth_csv, tmp_path):
    for m in ("lag", "linear"):
        run("train", "--model", m, "--data", synth_csv, *ARGS, "--out", str(tmp_path / m))
    rep = tmp_path / "r.md"
    run("compare", "--runs", str(tmp_path / "lag"), str(tmp_path / "linear"), "--out", str(rep))
    lines = [l for l in rep.read_text().splitlines() if l.startswith("|")]
    assert len(lines) == 4 and "val_rmse_usd" in lines[0]
    rm = [float(l.split("|")[-2]) for l in lines[2:]]
    assert rm == sorted(rm)


def test_r1_errors(synth_csv, tmp_path):
    assert run("compare", "--runs", str(tmp_path / "nope"), "--out", str(tmp_path / "x.md"), check=False).returncode == 2
    r = run("train", "--model", "lag", "--data", synth_csv, "--input-steps", "5000", "--out", str(tmp_path / "e"), check=False)
    assert r.returncode == 2 and "too short" in r.stderr
    assert run("train", "--model", "bogus", "--data", synth_csv, "--out", "x", check=False).returncode != 0
    assert run("predict", "--run", str(tmp_path), "--data", synth_csv, "--out", "x.csv", check=False).returncode == 2
    assert run("--help").returncode == 0


def test_r12_predict_short_data(synth_csv, tmp_path):
    from conftest import write_csv
    run("train", "--model", "linear", "--data", synth_csv, *ARGS, "--out", str(tmp_path / "l"))
    short = tmp_path / "s.csv"
    write_csv(short, np.arange(10.0))
    r = run("predict", "--run", str(tmp_path / "l"), "--data", str(short), "--out", str(tmp_path / "f.csv"), check=False)
    assert r.returncode == 2
