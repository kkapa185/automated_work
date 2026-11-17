"""Benchmark runner: in-flight tasks are resumed on their session, never re-attempted."""
from __future__ import annotations

import asyncio
import importlib.util
import json
from pathlib import Path

import pytest

from registry import SessionRegistry
from schemas import SessionState, TaskInput, TaskStatus

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def runner(tmp_path, monkeypatch):
    monkeypatch.setenv("BENCH_STATE", str(tmp_path / "state"))
    spec = importlib.util.spec_from_file_location("bench_runner", ROOT / "benchmarks" / "runner.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    bench_dir = tmp_path / "benchmarks"
    bench_dir.mkdir()
    (bench_dir / "manifest.json").write_text(json.dumps({"benchmarks": [{"name": "a"}, {"name": "b"}, {"name": "c"}]}))
    monkeypatch.setattr(mod, "BENCH_DIR", bench_dir)
    monkeypatch.setattr(mod, "RESULTS", bench_dir / "results.jsonl")
    return mod


async def test_pending_work_resumes_in_flight_even_if_previously_finished(runner, tmp_path):
    state = runner.STATE
    state.mkdir(parents=True)
    reg = SessionRegistry(state / "orchestrator.db")
    await reg.create_task(SessionState(task_id="t-a", workspace_path="/x", task_input=TaskInput(description="d")))
    await reg.bind_session("t-a", "sess-a")
    await reg.update_status("t-a", TaskStatus.PAUSED_USAGE_LIMIT)
    await reg.create_task(SessionState(task_id="t-b", workspace_path="/y", task_input=TaskInput(description="d")))
    await reg.update_status("t-b", TaskStatus.COMPLETED)
    reg.close()
    runner.save_state({"a": {"attempt": 2, "task_id": "t-a", "done": True}, "b": {"attempt": 1, "task_id": "t-b", "done": True}})
    # "a" has a finished attempt 1 in results but attempt 2 is paused in flight
    runner.RESULTS.write_text(json.dumps({"name": "a"}) + "\n" + json.dumps({"name": "b"}) + "\n")
    resume, start = await runner.pending_work()
    assert [b["name"] for b in resume] == ["a"]
    assert [b["name"] for b in start] == ["c"]
    resume, start = await runner.pending_work(force_names={"b"})
    assert [b["name"] for b in start] == ["b", "c"]


async def test_in_flight_helper(runner, tmp_path):
    reg = SessionRegistry(tmp_path / "x.db")
    assert not await runner.in_flight(reg, None)
    assert not await runner.in_flight(reg, "missing")
    await reg.create_task(SessionState(task_id="t", workspace_path="/x", task_input=TaskInput(description="d")))
    assert await runner.in_flight(reg, "t")
    await reg.update_status("t", TaskStatus.FAILED)
    assert not await runner.in_flight(reg, "t")
    reg.close()
