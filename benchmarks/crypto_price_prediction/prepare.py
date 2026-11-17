"""Place the offline BTC hourly dataset into the workspace."""
import argparse
import shutil
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument("--workspace", required=True)
p.add_argument("--reference", required=True)
a = p.parse_args()
dst = Path(a.workspace) / "data"
dst.mkdir(parents=True, exist_ok=True)
shutil.copy2("/home/user/bench_state/datasets/coinbase-1h-btc-usd.csv", dst / "btc_1h.csv")
