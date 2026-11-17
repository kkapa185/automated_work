from __future__ import annotations

import json
import os
import stat
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from claude_session import ClaudeSessionManager  # noqa: E402
from config import Settings  # noqa: E402
from orchestrator import TaskOrchestrator  # noqa: E402
from registry import SessionRegistry  # noqa: E402

FAKE = ROOT / "tests" / "fake_claude.py"


@dataclass
class FakeClaude:
    binary: Path
    scenario_path: Path
    log_path: Path

    def set_scenario(self, scenario: dict[str, Any]) -> None:
        self.scenario_path.write_text(json.dumps(scenario))

    def calls(self) -> list[dict[str, Any]]:
        if not self.log_path.exists():
            return []
        return [json.loads(line) for line in self.log_path.read_text().splitlines() if line.strip()]

    def argvs(self) -> list[list[str]]:
        return [c["argv"] for c in self.calls()]

    def children(self) -> list[int]:
        p = Path(str(self.log_path) + ".children")
        return [int(x) for x in p.read_text().split()] if p.exists() else []


@pytest.fixture
def fake_claude(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FakeClaude:
    binary = tmp_path / "bin" / "claude"
    binary.parent.mkdir()
    binary.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{FAKE}" "$@"\n')
    binary.chmod(binary.stat().st_mode | stat.S_IEXEC)
    fc = FakeClaude(binary, tmp_path / "scenario.json", tmp_path / "claude_calls.jsonl")
    fc.set_scenario({"session_id": "sess-abc", "calls": []})
    monkeypatch.setenv("FAKE_CLAUDE_SCENARIO", str(fc.scenario_path))
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(fc.log_path))
    return fc


@dataclass
class Sleeps:
    delays: list[float] = field(default_factory=list)

    async def __call__(self, d: float) -> None:
        self.delays.append(d)


@pytest.fixture
def sleeps() -> Sleeps:
    return Sleeps()


@pytest.fixture
def settings(tmp_path: Path, fake_claude: FakeClaude) -> Settings:
    return Settings(
        claude_binary=str(fake_claude.binary),
        workspace_root=tmp_path / "workspaces",
        db_path=tmp_path / "state" / "orch.db",
        cli_timeout_s=20,
        verify_timeout_s=60,
        kill_grace_s=1,
        max_turns=5,
        max_transient_retries=3,
        backoff_base_s=0.01,
        backoff_max_s=0.05,
    )


@pytest.fixture
def registry(settings: Settings):
    reg = SessionRegistry(settings.db_path)
    yield reg
    reg.close()


@pytest.fixture
def orchestrator(settings: Settings, registry: SessionRegistry, sleeps: Sleeps) -> TaskOrchestrator:
    sessions = ClaudeSessionManager(settings, registry, sleep=sleeps)
    return TaskOrchestrator(settings, registry, sessions=sessions)


def check_cmd(marker: str = "status.txt") -> str:
    """A verification command that passes only when ``marker`` contains 'pass'."""
    code = f"import sys,os; sys.exit(0 if os.path.exists('{marker}') and open('{marker}').read().strip()=='pass' else 1)"
    return f'{sys.executable} -c "{code}"'


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    # A zombie still answers kill(0); check /proc state.
    try:
        with open(f"/proc/{pid}/stat") as fh:
            return fh.read().split()[2] != "Z"
    except FileNotFoundError:
        return False
