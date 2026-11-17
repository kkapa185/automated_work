"""Provide the public TodoMVC application specification (not the test-suite or example apps)."""
import argparse
import shutil
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument("--workspace", required=True)
p.add_argument("--reference", required=True)
a = p.parse_args()
(Path(a.workspace) / "spec").mkdir(parents=True, exist_ok=True)
shutil.copy2(Path(a.reference) / "app-spec.md", Path(a.workspace) / "spec" / "app-spec.md")
