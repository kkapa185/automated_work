"""Provide the mal process guide and per-step pseudocode (public process docs), not tests or implementations."""
import argparse
import shutil
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument("--workspace", required=True)
p.add_argument("--reference", required=True)
a = p.parse_args()
dst = Path(a.workspace) / "docs"
dst.mkdir(parents=True, exist_ok=True)
for f in (Path(a.reference) / "process").iterdir():
    if f.suffix in (".md", ".txt"):
        shutil.copy2(f, dst / f.name)
