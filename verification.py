"""External verification gate: run test suites, linters and builds in the workspace."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import sys
import tempfile
from pathlib import Path

import asyncio
import contextlib
import time

import httpx
from pydantic import BaseModel, Field, ValidationError, field_validator

from process import run_process, terminate_process
from schemas import CommandResult, VerificationReport

CONTRACT_PATH = Path(".orchestrator") / "verify.json"
# Commands that cannot possibly verify anything; declaring them as the test suite is rejected.
NOOP_COMMANDS = frozenset({"true", ":", "echo", "exit", "printf", "sleep", "false"})


class SmokeSpec(BaseModel):
    command: str
    url: str | None = None
    timeout_s: float = Field(default=60.0, gt=0, le=1800)


class VerifyContract(BaseModel):
    setup: list[str] = Field(default_factory=list)
    test: list[str] = Field(default_factory=list)
    build: list[str] = Field(default_factory=list)
    lint: list[str] = Field(default_factory=list)
    smoke: list[SmokeSpec] = Field(default_factory=list)

    @field_validator("setup", "test", "build", "lint", mode="before")
    @classmethod
    def _listify(cls, v):  # type: ignore[no-untyped-def]
        if v is None:
            return []
        if isinstance(v, str):
            return [v]
        return [c for c in v if isinstance(c, str) and c.strip()]

    @field_validator("smoke", mode="before")
    @classmethod
    def _smoke(cls, v):  # type: ignore[no-untyped-def]
        if v is None:
            return []
        if isinstance(v, (str, dict)):
            v = [v]
        return [{"command": x} if isinstance(x, str) else x for x in v]


def load_contract(workspace: str | Path) -> tuple[VerifyContract | None, str | None]:
    """Return (contract, error). (None, None) means no contract file exists."""
    path = Path(workspace) / CONTRACT_PATH
    if not path.is_file():
        return None, None
    try:
        return VerifyContract.model_validate(json.loads(path.read_text() or "{}")), None
    except (json.JSONDecodeError, ValidationError, OSError) as exc:
        return None, f"{CONTRACT_PATH} is invalid: {exc}"


def is_noop(command: str) -> bool:
    try:
        argv = shlex.split(command)
    except ValueError:
        return False
    return not argv or Path(argv[0]).name in NOOP_COMMANDS


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

    def _env(self, env: dict[str, str] | None) -> dict[str, str]:
        full_env = dict(os.environ)
        full_env.update(env or {})
        full_env.setdefault("CI", "1")
        return full_env

    async def run_command(self, command: str, workspace: str, env: dict[str, str] | None = None,
                          kind: str = "check") -> CommandResult:
        res = await self._run_command(command, workspace, env)
        res.kind = kind
        return res

    async def _run_command(self, command: str, workspace: str, env: dict[str, str] | None = None) -> CommandResult:
        try:
            argv = shlex.split(command)
        except ValueError as exc:
            return CommandResult(command=command, exit_code=None, error=f"cannot parse command: {exc}")
        if not argv:
            return CommandResult(command=command, exit_code=None, error="empty command")
        full_env = self._env(env)
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

    async def run_server_smoke(self, spec: SmokeSpec, workspace: str, env: dict[str, str] | None = None) -> CommandResult:
        """Start a long-running command, wait until ``spec.url`` answers (< 500), then stop it."""
        label = f"{spec.command}  [smoke: {spec.url}]"
        try:
            argv = shlex.split(spec.command)
        except ValueError as exc:
            return CommandResult(command=label, kind="smoke", exit_code=None, error=f"cannot parse command: {exc}")
        if not argv:
            return CommandResult(command=label, kind="smoke", exit_code=None, error="empty command")
        start = time.monotonic()
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv, cwd=workspace, env=self._env(env), stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, start_new_session=True,
            )
        except FileNotFoundError:
            return CommandResult(command=label, kind="smoke", exit_code=127, error=f"command not found: {argv[0]}")
        out_task = asyncio.ensure_future(proc.stdout.read())  # type: ignore[union-attr]
        err_task = asyncio.ensure_future(proc.stderr.read())  # type: ignore[union-attr]
        status: int | None = None
        last_err = ""
        try:
            async with httpx.AsyncClient(timeout=5.0, trust_env=False) as client:
                while time.monotonic() - start < spec.timeout_s:
                    if proc.returncode is not None:
                        break
                    try:
                        resp = await client.get(spec.url)  # type: ignore[arg-type]
                        status = resp.status_code
                        if status < 500:
                            break
                        last_err = f"HTTP {status}"
                    except httpx.HTTPError as exc:
                        last_err = f"{type(exc).__name__}: {exc}"
                    with contextlib.suppress(asyncio.TimeoutError):
                        await asyncio.wait_for(proc.wait(), timeout=0.5)
        finally:
            exited_early = proc.returncode is not None
            await terminate_process(proc, self.kill_grace_s)
            out = (await out_task).decode("utf-8", "replace")
            err = (await err_task).decode("utf-8", "replace")
        ok = status is not None and status < 500
        error = None
        if not ok:
            if exited_early:
                error = f"server process exited with code {proc.returncode} before {spec.url} answered"
            else:
                error = f"{spec.url} did not answer within {spec.timeout_s:.0f}s ({last_err or 'no response'})"
        return CommandResult(
            command=label, kind="smoke", exit_code=0 if ok else (proc.returncode if exited_early else None),
            stdout=_tail(out, self.max_output_chars), stderr=_tail(err, self.max_output_chars),
            duration_s=time.monotonic() - start, timed_out=False, error=error,
        )

    async def verify(
        self, workspace: str, commands: list[str] | None = None, env: dict[str, str] | None = None,
        stop_on_failure: bool = False,
    ) -> VerificationReport:
        """Precedence: explicit commands > `.orchestrator/verify.json` contract > auto-detection."""
        if commands:
            return await self._run_list([(c, "check") for c in commands], workspace, env, stop_on_failure)

        contract, error = load_contract(workspace)
        if error:
            return VerificationReport.from_results([], reason=error)
        if contract is not None:
            return await self._verify_contract(contract, workspace, env, stop_on_failure)

        cmds = detect_commands(workspace)
        if not cmds:
            return VerificationReport.from_results(
                [], reason=(
                    "no verification suite found: create .orchestrator/verify.json (or a standard test "
                    "configuration) declaring how to install, test, build and smoke-run the project"
                ),
            )
        return await self._run_list([(c, "check") for c in cmds], workspace, env, stop_on_failure)

    async def _run_list(self, items: list[tuple[str, str]], workspace: str, env: dict[str, str] | None,
                        stop_on_failure: bool, reason: str | None = None) -> VerificationReport:
        results: list[CommandResult] = []
        for cmd, kind in items:
            r = await self.run_command(cmd, workspace, env, kind=kind)
            results.append(r)
            if not r.passed and (stop_on_failure or kind == "setup"):
                break
        return VerificationReport.from_results(results, reason=reason)

    async def _verify_contract(self, c: VerifyContract, workspace: str, env: dict[str, str] | None,
                               stop_on_failure: bool) -> VerificationReport:
        real_tests = [t for t in c.test if not is_noop(t)]
        if not real_tests:
            return VerificationReport.from_results(
                [], reason=f"{CONTRACT_PATH} declares no real test command in `test` (no-op commands are rejected)")
        items = [(x, "setup") for x in c.setup] + [(x, "build") for x in c.build] + \
                [(x, "test") for x in real_tests] + [(x, "lint") for x in c.lint]
        report = await self._run_list(items, workspace, env, stop_on_failure)
        results = list(report.results)
        if any(r.kind == "setup" and not r.passed for r in results):
            return VerificationReport.from_results(results, reason="setup command failed")
        if stop_on_failure and not report.passed:
            return report
        for spec in c.smoke:
            if spec.url:
                results.append(await self.run_server_smoke(spec, workspace, env))
            else:
                r = await self.run_command(spec.command, workspace, env, kind="smoke")
                results.append(r)
        return VerificationReport.from_results(results)
