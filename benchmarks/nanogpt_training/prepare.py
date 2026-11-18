"""Place the tiny-Shakespeare corpus (training data) in the workspace."""
import argparse
import shutil
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument("--workspace", required=True)
p.add_argument("--reference", required=True)
a = p.parse_args()
(Path(a.workspace) / "data").mkdir(parents=True, exist_ok=True)
shutil.copy2("/home/user/bench_state/datasets/shakespeare/input.txt", Path(a.workspace) / "data" / "input.txt")
