"""External verification gate: run test suites, linters and builds in the workspace."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import sys
import tempfile
from pathlib import Path

from process import run_process
from schemas import CommandResult, VerificationReport


def _tail(text: str, limit: int) -> str:
    return text if len(text) <= limit else "...[truncated]...\n" + text[-limit:]


def detect_commands(workspace: str | Path) -> list[str]:
    """Infer the checks to run from the project files present in the workspace."""
    ws = Path(workspace)
    cmds: list[str] = []

    pkg = ws / "package.json"
    if pkg.is_file():
        try:
            scripts = (json.loads(pkg.read_text() or "{}").get("scripts") or {})
        except (json.JSONDecodeError, OSError):
            scripts = {}
        if not (ws / "node_modules").exists() and shutil.which("npm"):
            cmds.append("npm install --no-audit --no-fund")
        if "lint" in scripts:
            cmds.append("npm run lint --silent")
        if "build" in scripts:
            cmds.append("npm run build --silent")
        if "test" in scripts and "no test specified" not in scripts["test"]:
            cmds.append("npm test --silent")

    py_markers = ("pyproject.toml", "pytest.ini", "setup.cfg", "setup.py", "tox.ini", "conftest.py")
    has_py_tests = (ws / "tests").is_dir() or any(ws.glob("test_*.py")) or any(ws.glob("*_test.py"))
    if has_py_tests or any((ws / m).is_file() for m in py_markers):
        if has_py_tests or (ws / "pytest.ini").is_file() or (ws / "conftest.py").is_file():
            cmds.append(f"{shlex.quote(sys.executable)} -m pytest -q")

    if (ws / "Cargo.toml").is_file():
        cmds.append("cargo build --quiet")
        cmds.append("cargo test --quiet")
    if (ws / "go.mod").is_file():
        cmds.append("go vet ./...")
        cmds.append("go test ./...")

    makefile = ws / "Makefile"
    if not cmds and makefile.is_file():
        try:
            text = makefile.read_text()
        except OSError:
            text = ""
        if any(line.startswith("test:") for line in text.splitlines()):
            cmds.append("make test")
    return cmds


class VerificationRunner:
    def __init__(self, timeout_s: float = 900.0, max_output_chars: int = 20_000, kill_grace_s: float = 5.0):
        self.timeout_s = timeout_s
        self.max_output_chars = max_output_chars
        self.kill_grace_s = kill_grace_s

    async def run_command(self, command: str, workspace: str, env: dict[str, str] | None = None) -> CommandResult:
        try:
            argv = shlex.split(command)
        except ValueError as exc:
            return CommandResult(command=command, exit_code=None, error=f"cannot parse command: {exc}")
        if not argv:
            return CommandResult(command=command, exit_code=None, error="empty command")
        full_env = dict(os.environ)
        full_env.update(env or {})
        full_env.setdefault("CI", "1")
        # Edits made within the same second (same size, same mtime) can leave stale .pyc files that
        # mask a fix, so every verification run compiles into a fresh, throw-away bytecode cache.
        with tempfile.TemporaryDirectory(prefix="orch-pycache-") as pycache:
            full_env["PYTHONPYCACHEPREFIX"] = pycache
            try:
                res = await run_process(
                    argv, cwd=workspace, env=full_env, timeout_s=self.timeout_s, kill_grace_s=self.kill_grace_s
                )
            except FileNotFoundError:
                return CommandResult(command=command, exit_code=127, error=f"command not found: {argv[0]}")
            except PermissionError as exc:
                return CommandResult(command=command, exit_code=126, error=f"permission denied: {exc}")
        return CommandResult(
            command=command,
            exit_code=res.exit_code,
            stdout=_tail(res.stdout, self.max_output_chars),
            stderr=_tail(res.stderr, self.max_output_chars),
            duration_s=res.duration_s,
            timed_out=res.timed_out,
        )

    async def verify(
        self, workspace: str, commands: list[str] | None = None, env: dict[str, str] | None = None,
        stop_on_failure: bool = False,
    ) -> VerificationReport:
        cmds = commands if commands else detect_commands(workspace)
        if not cmds:
            return VerificationReport.from_results(
                [], reason="no verification suite found in the workspace (add tests and a test runner config)"
            )
        results: list[CommandResult] = []
        for cmd in cmds:
            r = await self.run_command(cmd, workspace, env)
            results.append(r)
            if stop_on_failure and not r.passed:
                break
        return VerificationReport.from_results(results)
