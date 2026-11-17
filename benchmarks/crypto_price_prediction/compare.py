"""Hidden acceptance harness: run generated `./btcpredict` and the reference port under the same protocol."""
import argparse
import json
import subprocess


class _Failed:
    def __init__(self, exc):
        self.returncode, self.stdout, self.stderr = -1, "", repr(exc)


def run(*args, **kw):
    """subprocess.run that reports a missing/broken entry point as a failed check instead of crashing."""
    try:
        return subprocess.run(*args, **kw)
    except (OSError, subprocess.SubprocessError) as exc:
        return _Failed(exc)
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = "/home/user/bench_state/datasets/coinbase-1h-btc-usd.csv"
MODELS = ["lag", "linear", "cnn", "lstm", "gru"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", required=True)
    ap.add_argument("--reference", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--epochs", type=int, default=20)
    a = ap.parse_args()
    app = Path(a.app)
    ref_cache = Path("/home/user/bench_state/crypto_reference_metrics.json")
    if not ref_cache.exists():
        subprocess.run([sys.executable, str(HERE / "reference_run.py"), "--reference", a.reference, "--data", DATA,
                        "--epochs", str(a.epochs), "--out", str(ref_cache)], check=True)
    ref = json.loads(ref_cache.read_text())
    checks, got = [], {}
    for m in MODELS:
        out = app / "_bench_runs" / m
        try:
            proc = subprocess.run(["./btcpredict", "train", "--model", m, "--data", "data/btc_1h.csv", "--input-steps", "256",
                                   "--output-steps", "16", "--stride", "16", "--epochs", str(a.epochs), "--seed", "0",
                                   "--out", str(out)], cwd=app, capture_output=True, text=True, timeout=3600)
            rc, err = proc.returncode, proc.stderr[-800:]
        except Exception as exc:  # noqa: BLE001
            rc, err = -1, repr(exc)
        mpath = out / "metrics.json"
        metrics = json.loads(mpath.read_text()) if mpath.exists() else {}
        got[m] = metrics
        checks.append({"name": f"{m}: train runs and writes metrics.json", "passed": rc == 0 and bool(metrics),
                       "detail": f"rc={rc} {err[-300:] if rc else ''}"})
        r = ref[m]
        same_split = metrics.get("n_train") == r["n_train"] and metrics.get("n_val") == r["n_val"]
        checks.append({"name": f"{m}: identical sample split (n_train/n_val)", "passed": same_split,
                       "detail": f"got {metrics.get('n_train')}/{metrics.get('n_val')} ref {r['n_train']}/{r['n_val']}"})
        g = metrics.get("val_mse_usd")
        if m in ("lag", "linear"):
            ok = g is not None and abs(g - r["val_mse_usd"]) <= 0.01 * r["val_mse_usd"]
            checks.append({"name": f"{m}: deterministic baseline matches reference (±1%)", "passed": ok,
                           "detail": f"got {g} ref {r['val_mse_usd']:.1f}"})
        else:
            ok = g is not None and g <= 1.5 * r["val_mse_usd"]
            checks.append({"name": f"{m}: validation MSE (USD) within 1.5x of reference model", "passed": ok,
                           "detail": f"got {g} ref {r['val_mse_usd']:.1f}"})
        png = list(out.glob("*.png")) if out.exists() else []
        if m in ("cnn", "lstm", "gru"):
            checks.append({"name": f"{m}: prediction plot produced", "passed": bool(png), "detail": str([p.name for p in png])})
    # predict + compare commands
    fc = app / "_bench_runs" / "forecast.csv"
    p = run(["./btcpredict", "predict", "--run", str(app / "_bench_runs" / "lstm"), "--data", "data/btc_1h.csv",
                        "--out", str(fc)], cwd=app, capture_output=True, text=True, timeout=600)
    rows = fc.read_text().strip().splitlines() if fc.exists() else []
    checks.append({"name": "predict: forecasts output_steps values after last candle", "passed": p.returncode == 0 and len(rows) >= 16,
                   "detail": f"rc={p.returncode} rows={len(rows)}"})
    rep = app / "_bench_runs" / "report.md"
    p = run(["./btcpredict", "compare", "--runs", *[str(app / "_bench_runs" / m) for m in MODELS], "--out", str(rep)],
                       cwd=app, capture_output=True, text=True, timeout=300)
    text = rep.read_text() if rep.exists() else ""
    checks.append({"name": "compare: results table covers all models", "passed": p.returncode == 0 and all(m in text.lower() for m in MODELS),
                   "detail": f"rc={p.returncode}"})
    score = sum(c["passed"] for c in checks) / len(checks)
    result = {"score": round(score, 4), "checks": checks, "generated": got, "reference": ref}
    Path(a.out).write_text(json.dumps(result, indent=2))
    print(json.dumps({"score": result["score"], "failed": [c for c in checks if not c["passed"]]}, indent=2))


if __name__ == "__main__":
    main()
