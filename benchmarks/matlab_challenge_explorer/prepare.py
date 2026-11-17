"""Copy the hub content (without the generated catalog / explorer, which are the expected outputs)."""
import argparse
import shutil
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument("--workspace", required=True)
p.add_argument("--reference", required=True)
a = p.parse_args()
ref = Path(a.reference)
dst = Path(a.workspace) / "hub"
EXCLUDE = {".git", ".github", "table.html", "projects.json", "allSubmissions.json"}
shutil.copytree(ref, dst, ignore=lambda d, names: {n for n in names if n in EXCLUDE})
