from __future__ import annotations

import asyncio
import json
import sys
import time

import pytest

from claude_session import (
    ClaudeFatalError, ClaudeSessionManager, ClaudeTransientError, classify_failure, parse_cli_json,
)
from process import ProcessResult, run_process
from registry import SessionInvariantError
from schemas import SafetyLevel, SessionState, TaskInput, TaskStatus

from tests.conftest import pid_alive

SID = "sess-abc"


async def new_task(registry, settings, **kw) -> SessionState:
    import uuid
    tid = str(uuid.uuid4())
    ws = settings.workspace_root / tid
    ws.mkdir(parents=True)
    return await registry.create_task(SessionState(task_id=tid, workspace_path=str(ws), task_input=TaskInput(description="d", **kw)))


def test_build_argv_start_and_resume(settings, registry):
    sm = ClaudeSessionManager(settings.model_copy(update={"model": "opus", "claude_extra_args": ["--verbose"]}), registry)
    t = TaskInput(description="x")
    start = sm.build_argv("hello", None, t)
    assert start[:3] == [settings.claude_binary, "-p", "hello"]
    assert start[start.index("--output-format") + 1] == "json"
    assert start[start.index("--model") + 1] == "opus"
    assert start[-1] == "--verbose"
    assert "--strict-mcp-config" in start
    assert "--strict-mcp-config" not in ClaudeSessionManager(settings.model_copy(update={"cli_isolate_mcp": False}), registry).build_argv("p", None, t)
    assert "--resume" not in start
    resume = sm.build_argv("again", SID, t)
    assert resume[:5] == [settings.claude_binary, "--resume", SID, "-p", "again"]
    assert sm.build_argv(None, SID, t)[3:5] == ["-p", "--output-format"]


def test_permission_mode_none_omitted(settings, registry):
    sm = ClaudeSessionManager(settings.model_copy(update={"permission_mode": None}), registry)
    assert "--permission-mode" not in sm.build_argv("p", None, TaskInput(description="x"))


def test_custom_safety_without_tools_falls_back_to_standard(settings, registry):
    sm = ClaudeSessionManager(settings, registry)
    assert sm.tools_for(TaskInput(description="x", safety=SafetyLevel.CUSTOM)) == settings.allowed_tools_standard


@pytest.mark.parametrize("stdout", [
    json.dumps({"type": "result", "session_id": SID, "result": "ok"}),
    "warming up...\n" + json.dumps({"type": "result", "session_id": SID, "result": "ok"}) + "\n",
    json.dumps([{"type": "system", "session_id": SID}, {"type": "result", "session_id": SID, "result": "ok"}]),
    json.dumps({"type": "result", "session_id": SID, "result": "ok", "usage": None, "new_field": 1}),
])
def test_parse_cli_json_variants(stdout):
    r = parse_cli_json(stdout)
    assert r is not None and r.session_id == SID and r.result == "ok"


@pytest.mark.parametrize("stdout", ["", "not json", '{"type": "result"}', "[1, 2]"])
def test_parse_cli_json_rejects(stdout):
    assert parse_cli_json(stdout) is None


def test_parse_usage_and_extra_fields():
    r = parse_cli_json(json.dumps({
        "session_id": SID, "usage": {"input_tokens": 5, "output_tokens": 7, "server_tool_use": {}},
        "total_cost_usd": 0.5, "modelUsage": {"x": 1},
    }))
    assert r.usage.total == 12 and r.total_cost_usd == 0.5 and r.model_extra["modelUsage"] == {"x": 1}


def _proc(exit_code=0, stdout="", stderr="", timed_out=False):
    return ProcessResult(argv=[], exit_code=exit_code, stdout=stdout, stderr=stderr, duration_s=0, timed_out=timed_out)


def test_classify_failure():
    ok = parse_cli_json(json.dumps({"session_id": SID, "result": "fine"}))
    overloaded = parse_cli_json(json.dumps({"session_id": SID, "is_error": True, "result": "API Error: 529 Overloaded"}))
    max_turns = parse_cli_json(json.dumps({"session_id": SID, "is_error": True, "subtype": "error_max_turns"}))
    assert classify_failure(_proc(), ok) is None
    assert classify_failure(_proc(timed_out=True), None) is ClaudeTransientError
    assert classify_failure(_proc(), overloaded) is ClaudeTransientError
    assert classify_failure(_proc(), max_turns) is None
    assert classify_failure(_proc(1, stderr="Invalid API key · Please run /login"), None) is ClaudeFatalError
    assert classify_failure(_proc(1, stderr="fetch failed: ECONNRESET"), None) is ClaudeTransientError
    assert classify_failure(_proc(1, stderr="segfault"), None) is ClaudeFatalError
    assert classify_failure(_proc(0, stdout="garbled"), None) is ClaudeTransientError
    assert classify_failure(_proc(1), ok) is None


async def test_send_binds_then_resumes(settings, registry, fake_claude, sleeps):
    st = await new_task(registry, settings)
    sm = ClaudeSessionManager(settings, registry, sleep=sleeps)
    o1 = await sm.send(st.task_id, "one", TaskStatus.PLANNING)
    o2 = await sm.send(st.task_id, "two", TaskStatus.IMPLEMENTING)
    assert o1.result.session_id == o2.result.session_id == SID
    assert not o1.turn.resumed and o2.turn.resumed
    assert o2.state.turn_count == 2 and (await registry.get(st.task_id)).session_id == SID
    argvs = fake_claude.argvs()
    assert "--resume" not in argvs[0] and argvs[1][0:2] == ["--resume", SID]


async def test_pre_bound_session_is_never_restarted(settings, registry, fake_claude, sleeps):
    st = await new_task(registry, settings)
    await registry.bind_session(st.task_id, "sess-existing")
    sm = ClaudeSessionManager(settings, registry, sleep=sleeps)
    await sm.send(st.task_id, "x", TaskStatus.HEALING)
    assert fake_claude.argvs()[0][0:2] == ["--resume", "sess-existing"]


async def test_concurrent_sends_are_serialized_and_share_session(settings, registry, fake_claude, sleeps):
    fake_claude.set_scenario({"session_id": SID, "default": {"sleep": 0.2}})
    st = await new_task(registry, settings)
    sm = ClaudeSessionManager(settings, registry, sleep=sleeps)
    outs = await asyncio.gather(*(sm.send(st.task_id, f"p{i}", TaskStatus.HEALING) for i in range(3)))
    argvs = fake_claude.argvs()
    assert sum("--resume" not in a for a in argvs) == 1
    assert {o.result.session_id for o in outs} == {SID}
    assert sorted(o.turn.turn_index for o in outs) == [1, 2, 3]
    # Serialized: invocations never overlapped (each logged after the previous finished).
    assert len(argvs) == 3


async def test_session_mismatch_raises(settings, registry, fake_claude, sleeps):
    fake_claude.set_scenario({"session_id": SID, "calls": [{}, {"session_id": "other"}]})
    st = await new_task(registry, settings)
    sm = ClaudeSessionManager(settings, registry, sleep=sleeps)
    await sm.send(st.task_id, "a", TaskStatus.PLANNING)
    with pytest.raises(SessionInvariantError):
        await sm.send(st.task_id, "b", TaskStatus.IMPLEMENTING)
    assert (await registry.get(st.task_id)).turn_count == 1


async def test_timeout_is_transient_and_kills_process_group(settings, registry, fake_claude, sleeps):
    s = settings.model_copy(update={"cli_timeout_s": 1.0, "max_transient_retries": 1, "kill_grace_s": 0.5})
    fake_claude.set_scenario({"session_id": SID, "default": {"spawn_child": True, "sleep": 30}})
    st = await new_task(registry, s)
    sm = ClaudeSessionManager(s, registry, sleep=sleeps)
    t0 = time.monotonic()
    with pytest.raises(ClaudeTransientError, match="timed out"):
        await sm.send(st.task_id, "x", TaskStatus.PLANNING)
    assert time.monotonic() - t0 < 10
    assert len(fake_claude.argvs()) == 2 and len(sleeps.delays) == 1
    await asyncio.sleep(0.2)
    for pid in [c["pid"] for c in fake_claude.calls()] + fake_claude.children():
        assert not pid_alive(pid), f"process {pid} survived"


async def test_run_process_cancellation_reaps_children(tmp_path):
    marker = tmp_path / "pid"
    code = f"import subprocess,sys,time; p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(600)']); open(r'{marker}','w').write(str(p.pid)); time.sleep(600)"
    task = asyncio.create_task(run_process([sys.executable, "-c", code], timeout_s=60, kill_grace_s=0.5))
    for _ in range(100):
        if marker.exists() and marker.read_text():
            break
        await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.sleep(0.2)
    assert not pid_alive(int(marker.read_text()))


async def test_run_process_streams_lines_and_large_output(tmp_path):
    lines: list[tuple[str, str]] = []
    code = "import sys; print('a'); print('x'*200000); sys.stderr.write('err-line'); print('z', end='')"
    r = await run_process([sys.executable, "-c", code], on_line=lambda s, l: lines.append((s, l)))
    assert r.exit_code == 0 and len(r.stdout) > 200000
    assert ("stdout", "a") in lines and ("stdout", "z") in lines and ("stderr", "err-line") in lines


async def test_run_process_stdin(tmp_path):
    r = await run_process([sys.executable, "-c", "import sys; print(sys.stdin.read().upper())"], stdin_data=b"hey")
    assert r.stdout.strip() == "HEY"


async def test_fatal_binary_missing(settings, registry, sleeps):
    st = await new_task(registry, settings)
    sm = ClaudeSessionManager(settings.model_copy(update={"claude_binary": "/no/such/claude"}), registry, sleep=sleeps)
    with pytest.raises(ClaudeFatalError, match="not found"):
        await sm.send(st.task_id, "x", TaskStatus.PLANNING)


async def test_extra_env_is_passed(settings, registry, fake_claude, sleeps):
    st = await new_task(registry, settings, extra_env={"MY_FLAG": "42"})
    sm = ClaudeSessionManager(settings, registry, sleep=sleeps)
    env = sm._env(st.task_input)
    assert env["MY_FLAG"] == "42" and "PATH" in env


# ------------------------------------------------------------------ pre-assigned session ids

async def test_preassigned_session_id_used_and_bound(settings, registry, fake_claude, sleeps):
    s = settings.model_copy(update={"preassign_session_id": True})
    st = await new_task(registry, s)
    sm = ClaudeSessionManager(s, registry, sleep=sleeps)
    out = await sm.send(st.task_id, "plan", TaskStatus.PLANNING)
    planned = (await registry.get(st.task_id)).planned_session_id
    assert planned and out.result.session_id == planned == (await registry.get(st.task_id)).session_id
    a0 = fake_claude.argvs()[0]
    assert a0[a0.index("--session-id") + 1] == planned and "--resume" not in a0
    await sm.send(st.task_id, "impl", TaskStatus.IMPLEMENTING)
    a1 = fake_claude.argvs()[1]
    assert a1[0:2] == ["--resume", planned] and "--session-id" not in a1


async def test_first_turn_timeout_is_retried_on_the_same_session(settings, registry, fake_claude, sleeps):
    """Session created, then the CLI hangs: the retry must adopt the planned id, not start a second session."""
    s = settings.model_copy(update={"preassign_session_id": True, "cli_timeout_s": 1.0, "kill_grace_s": 0.3})
    fake_claude.set_scenario({"calls": [{"sleep": 30}], "default": {}})
    st = await new_task(registry, s)
    sm = ClaudeSessionManager(s, registry, sleep=sleeps)
    out = await sm.send(st.task_id, "plan", TaskStatus.PLANNING)
    planned = (await registry.get(st.task_id)).planned_session_id
    argvs = fake_claude.argvs()
    # attempt 1 timed out; attempt 2 got "already in use"; attempt 3 resumed the planned session
    assert [("--resume" in a, a[a.index("--session-id") + 1] if "--session-id" in a else None) for a in argvs] == \
        [(False, planned), (False, planned), (True, None)]
    assert argvs[2][0:2] == ["--resume", planned]
    assert out.result.session_id == planned and out.turn.resumed


async def test_crash_before_session_creation_restarts_with_same_planned_id(settings, registry, fake_claude, sleeps):
    s = settings.model_copy(update={"preassign_session_id": True})
    fake_claude.set_scenario({"calls": [{"crash_before_session": True}], "default": {}})
    st = await new_task(registry, s)
    sm = ClaudeSessionManager(s, registry, sleep=sleeps)
    out = await sm.send(st.task_id, "plan", TaskStatus.PLANNING)
    planned = (await registry.get(st.task_id)).planned_session_id
    argvs = fake_claude.argvs()
    assert len(argvs) == 2 and all(a[a.index("--session-id") + 1] == planned for a in argvs)
    assert out.result.session_id == planned


async def test_planned_session_survives_restart(settings, registry, fake_claude, sleeps, tmp_path):
    s = settings.model_copy(update={"preassign_session_id": True})
    st = await new_task(registry, s)
    planned = await registry.plan_session(st.task_id, "11111111-2222-4333-8444-555555555555")
    assert await registry.plan_session(st.task_id, "other") == planned  # idempotent
    sm = ClaudeSessionManager(s, registry, sleep=sleeps)
    out = await sm.send(st.task_id, "plan", TaskStatus.PLANNING)
    assert out.result.session_id == planned


async def test_cli_ignoring_planned_id_violates_invariant(settings, registry, fake_claude, sleeps):
    s = settings.model_copy(update={"preassign_session_id": True})
    fake_claude.set_scenario({"calls": [{"session_id": "rogue"}]})
    st = await new_task(registry, s)
    sm = ClaudeSessionManager(s, registry, sleep=sleeps)
    with pytest.raises(SessionInvariantError):
        await sm.send(st.task_id, "plan", TaskStatus.PLANNING)
