"""Shared helpers for hidden comparison harnesses."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


class Failed:
    def __init__(self, exc: BaseException):
        self.returncode, self.stdout, self.stderr = -1, "", repr(exc)


def run(args, **kw):
    """subprocess.run that turns a missing/broken entry point into a failed result instead of raising."""
    kw.setdefault("capture_output", True)
    kw.setdefault("text", True)
    kw.setdefault("timeout", 600)
    try:
        return subprocess.run(args, **kw)
    except (OSError, subprocess.SubprocessError) as exc:
        return Failed(exc)


def run_python_driver(driver: str, pythonpath: str | Path, cwd: str | Path, payload: Any, timeout: int = 600) -> Any:
    """Execute a driver snippet with ``pythonpath`` first on sys.path; payload in on stdin, JSON out on stdout."""
    env = dict(os.environ, PYTHONPATH=str(pythonpath), PYTHONDONTWRITEBYTECODE="1")
    p = run([sys.executable, "-c", driver], input=json.dumps(payload), env=env, cwd=str(cwd), timeout=timeout)
    if p.returncode != 0:
        return {"__error__": (p.stderr or "")[-2000:]}
    try:
        return json.loads(p.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        return {"__error__": f"bad driver output: {p.stdout[-500:]}"}


def finish(out: str | Path, checks: list[dict[str, Any]], **extra: Any) -> None:
    score = sum(bool(c["passed"]) for c in checks) / len(checks) if checks else 0.0
    res = {"score": round(score, 4), "checks": checks, **extra}
    Path(out).write_text(json.dumps(res, indent=2, default=str))
    print(json.dumps({"score": res["score"], "failed": [c["name"] for c in checks if not c["passed"]]}, indent=2))


def check(name: str, passed: bool, detail: Any = "") -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "detail": str(detail)[:1000]}
