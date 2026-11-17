"""Provide the API contract (OpenAPI document) but not the conformance test collections."""
import argparse
import shutil
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument("--workspace", required=True)
p.add_argument("--reference", required=True)
a = p.parse_args()
(Path(a.workspace) / "spec").mkdir(parents=True, exist_ok=True)
shutil.copy2(Path(a.reference) / "specs" / "api" / "openapi.yml", Path(a.workspace) / "spec" / "openapi.yml")
