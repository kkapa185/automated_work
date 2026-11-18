"""Provide the CommonMark specification (the public, normative document)."""
import argparse
import shutil
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument("--workspace", required=True)
p.add_argument("--reference", required=True)
a = p.parse_args()
(Path(a.workspace) / "docs").mkdir(parents=True, exist_ok=True)
shutil.copy2(Path(a.reference) / "test" / "spec.txt", Path(a.workspace) / "docs" / "spec.txt")
