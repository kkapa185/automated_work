"""Copy the Apollo-11 AGC sources (the assembler's input data) into the benchmark workspace."""
import argparse
import shutil
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument("--workspace", required=True)
p.add_argument("--reference", required=True)
a = p.parse_args()
ref = Path(a.reference)
for prog in ("Comanche055", "Luminary099"):
    dst = Path(a.workspace) / "agc_source" / prog
    dst.mkdir(parents=True, exist_ok=True)
    for f in (ref / prog).glob("*.agc"):
        shutil.copy2(f, dst / f.name)
