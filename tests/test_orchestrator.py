"""End-to-end orchestrator tests against a scripted fake ``claude`` binary.

The central property: every turn after the first — self-healing retries, transient
retries and post-restart resumes — reuses exactly the same ``session_id``.
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path

import pytest

from claude_session import ClaudeSessionManager
from config import Settings
from orchestrator import TaskOrchestrator
from registry import DuplicateTaskError, SessionRegistry
from schemas import ContextSource, SafetyLevel, SourceKind, TaskInput, TaskStatus

from tests.conftest import check_cmd

SID = "sess-abc"


def assert_single_session(argvs: list[list[str]], sid: str = SID) -> None:
    """Exactly one start call (first), every other call resumes ``sid``."""
    assert argvs, "claude was never invoked"
    starts = [a for a in argvs if "--resume" not in a]
    assert len(starts) == 1, f"expected exactly 1 session start, got {len(starts)}"
    assert "--resume" not in argvs[0]
    for a in argvs[1:]:
        assert a[a.index("--resume") + 1] == sid
    for a in argvs:
        assert a[a.index("--output-format") + 1] == "json"
        assert "-p" in a


def task(**kw) -> TaskInput:
    kw.setdefault("description", "Fix the failing check")
    kw.setdefault("verification_commands", [check_cmd()])
    kw.setdefault("auto_detect_sources", False)
    return TaskInput(**kw)


async def run_to_end(orch: TaskOrchestrator, t: TaskInput, **kw):
    state = await orch.submit(t, **kw)
    summary = await orch.wait(state.task_id, timeout=60)
    assert summary is not None
    return state, summary


async def test_self_healing_retries_reuse_same_session(orchestrator, fake_claude, registry):
    fake_claude.set_scenario({
        "session_id": SID,
        "calls": [
            {"result": "PLAN: 1. write status"},
            {"write": {"status.txt": "fail"}, "result": "implemented"},
            {"write": {"status.txt": "still-fail"}, "result": "heal 1"},
            {"write": {"status.txt": "pass"}, "result": "heal 2: fixed root cause"},
        ],
    })
    state, summary = await run_to_end(orchestrator, task())

    argvs = fake_claude.argvs()
    assert len(argvs) == 4
    assert_single_session(argvs)
    assert summary.status == TaskStatus.COMPLETED
    assert summary.session_id == SID
    assert summary.turns_used == 4
    assert summary.final_message == "heal 2: fixed root cause"
    assert summary.verification and summary.verification.passed
    assert summary.token_usage.input_tokens == 400
    assert summary.total_cost_usd == pytest.approx(0.04)

    st = await registry.get(state.task_id)
    assert st.session_id == SID and st.turn_count == 4 and st.status == TaskStatus.COMPLETED
    turns = await registry.turns(state.task_id)
    assert [t.phase for t in turns] == [TaskStatus.PLANNING, TaskStatus.IMPLEMENTING, TaskStatus.HEALING, TaskStatus.HEALING]
    assert {t.session_id for t in turns} == {SID}
    assert [t.resumed for t in turns] == [False, True, True, True]
    # Every call ran in the task workspace.
    assert {c["cwd"] for c in fake_claude.calls()} == {st.workspace_path}


async def test_heal_prompt_contains_exact_failure_output(orchestrator, fake_claude):
    failing = f'{sys.executable} -c "import sys; print(\'OUT-MARKER\'); sys.stderr.write(\'AssertionError: ERR-MARKER\'); sys.exit(3)"'
    fake_claude.set_scenario({"session_id": SID, "calls": [{}, {}, {}]})
    _, summary = await run_to_end(orchestrator, task(verification_commands=[failing], max_turns=3))
    argvs = fake_claude.argvs()
    heal = argvs[2][argvs[2].index("-p") + 1]
    assert "ERR-MARKER" in heal and "OUT-MARKER" in heal and "exit code 3" in heal
    assert summary.status == TaskStatus.FAILED


async def test_success_on_first_verification_uses_two_turns(orchestrator, fake_claude):
    fake_claude.set_scenario({"session_id": SID, "calls": [{}, {"write": {"status.txt": "pass"}}]})
    _, summary = await run_to_end(orchestrator, task())
    assert summary.status == TaskStatus.COMPLETED
    assert summary.turns_used == 2
    assert_single_session(fake_claude.argvs())


async def test_max_turns_budget_exhausted(orchestrator, fake_claude, registry):
    fake_claude.set_scenario({"session_id": SID, "default": {"write": {"status.txt": "fail"}}})
    state, summary = await run_to_end(orchestrator, task(max_turns=4))
    argvs = fake_claude.argvs()
    assert len(argvs) == 4
    assert_single_session(argvs)
    assert summary.status == TaskStatus.FAILED
    assert summary.failure_reason.startswith("max_turns_exhausted")
    assert summary.turns_used == 4 and summary.max_turns == 4
    assert summary.verification is not None and not summary.verification.passed
    assert (await registry.get(state.task_id)).status == TaskStatus.FAILED


async def test_settings_max_turns_default_applies(settings, registry, sleeps, fake_claude):
    s = settings.model_copy(update={"max_turns": 3})
    orch = TaskOrchestrator(s, registry, sessions=ClaudeSessionManager(s, registry, sleep=sleeps))
    fake_claude.set_scenario({"session_id": SID, "default": {}})
    _, summary = await run_to_end(orch, task())
    assert len(fake_claude.argvs()) == 3 and summary.status == TaskStatus.FAILED


async def test_transient_errors_retry_on_same_session(orchestrator, fake_claude, sleeps):
    fake_claude.set_scenario({
        "session_id": SID,
        "calls": [
            {"exit_code": 1, "raw_stdout": "", "stderr": "API Error: 529 overloaded_error"},   # start fails, no session yet
            {"result": "plan"},                                                              # start retried
            {"is_error": True, "result": "API Error: 529 Overloaded"},                      # implement: transient
            {"exit_code": 1, "raw_stdout": "", "stderr": "Error: socket hang up ECONNRESET"},  # implement: transient
            {"write": {"status.txt": "pass"}},                                               # implement ok
        ],
    })
    state, summary = await run_to_end(orchestrator, task())
    argvs = fake_claude.argvs()
    assert len(argvs) == 5
    # Both start attempts happened before any session existed; afterwards everything resumes.
    assert "--resume" not in argvs[0] and "--resume" not in argvs[1]
    for a in argvs[2:]:
        assert a[a.index("--resume") + 1] == SID
    assert summary.status == TaskStatus.COMPLETED
    assert summary.turns_used == 2  # transient retries don't consume the turn budget
    assert len(sleeps.delays) == 3 and all(d > 0 for d in sleeps.delays)


async def test_transient_error_after_session_created_resumes_instead_of_restarting(orchestrator, fake_claude):
    # The very first call creates the session but reports an API overload: the retry must resume it.
    fake_claude.set_scenario({
        "session_id": SID,
        "calls": [{"is_error": True, "result": "API Error: 529 overloaded"}, {"result": "plan"},
                  {"write": {"status.txt": "pass"}}],
    })
    _, summary = await run_to_end(orchestrator, task())
    assert_single_session(fake_claude.argvs())
    assert summary.status == TaskStatus.COMPLETED


async def test_transient_retries_exhausted_fails_task(orchestrator, fake_claude, settings):
    fake_claude.set_scenario({"session_id": SID, "calls": [{}],
                              "default": {"exit_code": 1, "raw_stdout": "", "stderr": "429 rate limit"}})
    _, summary = await run_to_end(orchestrator, task())
    assert summary.status == TaskStatus.FAILED
    assert "ClaudeTransientError" in summary.failure_reason
    argvs = fake_claude.argvs()
    assert len(argvs) == 1 + settings.max_transient_retries + 1
    assert_single_session(argvs)


async def test_fatal_error_is_not_retried(orchestrator, fake_claude, sleeps):
    fake_claude.set_scenario({"session_id": SID, "default": {"exit_code": 1, "raw_stdout": "", "stderr": "Invalid API key"}})
    _, summary = await run_to_end(orchestrator, task())
    assert len(fake_claude.argvs()) == 1 and sleeps.delays == []
    assert summary.status == TaskStatus.FAILED and "ClaudeFatalError" in summary.failure_reason
    assert summary.session_id is None


async def test_session_id_change_violates_invariant(orchestrator, fake_claude):
    fake_claude.set_scenario({"session_id": SID, "calls": [{}, {"session_id": "sess-OTHER"}]})
    state, summary = await run_to_end(orchestrator, task())
    assert summary.status == TaskStatus.FAILED
    assert summary.failure_reason.startswith("session_invariant_violation")
    assert summary.session_id == SID  # never rebound
    assert len(fake_claude.argvs()) == 2


async def test_resume_after_restart_uses_stored_session(settings, fake_claude, sleeps):
    # Simulate a crash: the first orchestrator only gets through planning + implementation.
    fake_claude.set_scenario({"session_id": SID, "calls": [{}, {"write": {"status.txt": "fail"}}],
                              "default": {"write": {"status.txt": "pass"}}})
    reg1 = SessionRegistry(settings.db_path)
    orch1 = TaskOrchestrator(settings, reg1, sessions=ClaudeSessionManager(settings, reg1, sleep=sleeps))
    state = await orch1.submit(task(), start=False)
    sm = orch1.sessions
    await sm.send(state.task_id, "plan", TaskStatus.PLANNING)
    await sm.send(state.task_id, "implement", TaskStatus.IMPLEMENTING)
    await reg1.update_status(state.task_id, TaskStatus.HEALING)
    reg1.close()

    # "Restart": brand-new registry/orchestrator instances on the same database.
    reg2 = SessionRegistry(settings.db_path)
    orch2 = TaskOrchestrator(settings, reg2, sessions=ClaudeSessionManager(settings, reg2, sleep=sleeps))
    resumed = await orch2.resume_interrupted()
    assert resumed == [state.task_id]
    summary = await orch2.wait(state.task_id, timeout=60)
    reg2.close()

    argvs = fake_claude.argvs()
    assert len(argvs) == 3
    assert_single_session(argvs)
    assert summary.status == TaskStatus.COMPLETED and summary.session_id == SID and summary.turns_used == 3


async def test_resume_after_plan_only_continues_with_implementation(settings, fake_claude, sleeps, registry):
    fake_claude.set_scenario({"session_id": SID, "calls": [{}, {"write": {"status.txt": "pass"}}]})
    orch = TaskOrchestrator(settings, registry, sessions=ClaudeSessionManager(settings, registry, sleep=sleeps))
    state = await orch.submit(task(), start=False)
    await orch.sessions.send(state.task_id, "plan", TaskStatus.PLANNING)
    summary = await orch.run(state.task_id)
    argvs = fake_claude.argvs()
    assert_single_session(argvs)
    assert len(argvs) == 2
    implement_prompt = argvs[1][argvs[1].index("-p") + 1]
    assert "Phase 2" in implement_prompt
    assert summary.status == TaskStatus.COMPLETED


async def test_rerunning_completed_task_does_not_invoke_claude(orchestrator, fake_claude):
    fake_claude.set_scenario({"session_id": SID, "calls": [{}, {"write": {"status.txt": "pass"}}]})
    state, summary = await run_to_end(orchestrator, task())
    n = len(fake_claude.argvs())
    again = await orchestrator.run(state.task_id)
    assert again == summary and len(fake_claude.argvs()) == n


async def test_start_twice_returns_same_running_task(orchestrator, fake_claude):
    fake_claude.set_scenario({"session_id": SID, "calls": [{"sleep": 0.3}, {"write": {"status.txt": "pass"}}]})
    state = await orchestrator.submit(task(), start=False)
    t1 = orchestrator.start(state.task_id)
    t2 = orchestrator.start(state.task_id)
    assert t1 is t2
    await t1
    assert_single_session(fake_claude.argvs())
    assert len(fake_claude.argvs()) == 2


async def test_duplicate_task_id_rejected(orchestrator, fake_claude):
    tid = str(uuid.uuid4())
    await orchestrator.submit(task(), task_id=tid, start=False)
    with pytest.raises(DuplicateTaskError):
        await orchestrator.submit(task(), task_id=tid, start=False)


async def test_invalid_task_id_rejected(orchestrator):
    with pytest.raises(ValueError):
        await orchestrator.submit(task(), task_id="not-a-uuid", start=False)


async def test_task_ids_are_uuid4_and_workspaces_isolated(orchestrator, settings, fake_claude):
    s1 = await orchestrator.submit(task(), start=False)
    s2 = await orchestrator.submit(task(), start=False)
    assert uuid.UUID(s1.task_id).version == 4
    assert s1.workspace_path == str((settings.workspace_root / s1.task_id).resolve())
    assert s1.workspace_path != s2.workspace_path and Path(s1.workspace_path).is_dir()


async def test_concurrent_tasks_get_distinct_sessions(orchestrator, fake_claude, registry, tmp_path):
    # Task A is pre-bound to its own session; task B starts fresh. Their sessions must never mix.
    fake_claude.set_scenario({"session_id": SID, "default": {"write": {"status.txt": "pass"}}})
    a = await orchestrator.submit(task(), start=False)
    await registry.bind_session(a.task_id, "sess-A")  # pre-bound: everything resumes sess-A
    b = await orchestrator.submit(task(), start=False)
    await asyncio.gather(orchestrator.run(a.task_id), orchestrator.run(b.task_id))
    by_cwd: dict[str, set[str]] = {}
    for c in fake_claude.calls():
        argv = c["argv"]
        by_cwd.setdefault(c["cwd"], set()).add(argv[argv.index("--resume") + 1] if "--resume" in argv else "START")
    assert by_cwd[a.workspace_path] == {"sess-A"}
    assert by_cwd[b.workspace_path] == {"START", SID}


async def test_read_only_safety_restricts_tools(orchestrator, fake_claude):
    fake_claude.set_scenario({"session_id": SID, "calls": [{}, {"write": {"status.txt": "pass"}}]})
    await run_to_end(orchestrator, task(safety=SafetyLevel.READ_ONLY))
    for a in fake_claude.argvs():
        assert a[a.index("--allowedTools") + 1] == "Read,Glob,Grep"
        assert "Bash" in a[a.index("--disallowedTools") + 1]
        assert a[a.index("--permission-mode") + 1] == "default"


async def test_custom_and_standard_tools(orchestrator, fake_claude):
    fake_claude.set_scenario({"session_id": SID, "calls": [{}, {"write": {"status.txt": "pass"}}]})
    await run_to_end(orchestrator, task(safety=SafetyLevel.CUSTOM, allowed_tools=["Read", "Edit"]))
    assert all(a[a.index("--allowedTools") + 1] == "Read,Edit" for a in fake_claude.argvs())


async def test_standard_tools_default(orchestrator, fake_claude):
    fake_claude.set_scenario({"session_id": SID, "calls": [{}, {"write": {"status.txt": "pass"}}]})
    await run_to_end(orchestrator, task())
    a = fake_claude.argvs()[0]
    assert a[a.index("--allowedTools") + 1] == "Bash,Edit,Write,Read,Glob,Grep"
    assert a[a.index("--permission-mode") + 1] == "acceptEdits"


async def test_context_hydration_failures_do_not_abort(orchestrator, fake_claude, tmp_path):
    spec = tmp_path / "spec.md"
    spec.write_text("# Spec\nThe status file must say pass.")
    fake_claude.set_scenario({"session_id": SID, "calls": [{}, {"write": {"status.txt": "pass"}}]})
    t = task(
        description="Implement PROJ-42 according to the spec",
        auto_detect_sources=True,
        context_sources=[ContextSource(kind=SourceKind.FILE, ref=str(spec)),
                         ContextSource(kind=SourceKind.FILE, ref=str(tmp_path / "missing.md"))],
    )
    _, summary = await run_to_end(orchestrator, t)
    assert summary.status == TaskStatus.COMPLETED
    plan = fake_claude.argvs()[0][fake_claude.argvs()[0].index("-p") + 1]
    assert "The status file must say pass." in plan
    assert "<unavailable_sources>" in plan
    assert "jira PROJ-42: jira connector is not configured" in plan


async def test_large_prompt_is_piped_via_stdin(settings, registry, sleeps, fake_claude):
    s = settings.model_copy(update={"max_argv_prompt_bytes": 1000})
    orch = TaskOrchestrator(s, registry, sessions=ClaudeSessionManager(s, registry, sleep=sleeps))
    fake_claude.set_scenario({"session_id": SID, "calls": [{}, {"write": {"status.txt": "pass"}}]})
    _, summary = await run_to_end(orch, task(description="x" * 5000))
    first = fake_claude.calls()[0]
    assert first["stdin"] is not None and "x" * 5000 in first["stdin"]
    assert first["argv"][first["argv"].index("-p") + 1] == "--output-format"
    assert summary.status == TaskStatus.COMPLETED
    assert_single_session(fake_claude.argvs())


async def test_cancel_running_task(orchestrator, fake_claude, registry):
    fake_claude.set_scenario({"session_id": SID, "default": {"sleep": 30}})
    state = await orchestrator.submit(task())
    await asyncio.sleep(0.5)
    assert await orchestrator.cancel(state.task_id)
    st = await registry.get(state.task_id)
    assert st.status == TaskStatus.CANCELLED
    summary = await registry.get_summary(state.task_id)
    assert summary is not None and summary.status == TaskStatus.CANCELLED


async def test_missing_binary_fails_cleanly(settings, registry, sleeps):
    s = settings.model_copy(update={"claude_binary": "/nonexistent/claude"})
    orch = TaskOrchestrator(s, registry, sessions=ClaudeSessionManager(s, registry, sleep=sleeps))
    _, summary = await run_to_end(orch, task())
    assert summary.status == TaskStatus.FAILED and "binary not found" in summary.failure_reason


async def test_auto_detected_pytest_suite_end_to_end(orchestrator, fake_claude):
    """Claude writes real code + tests; the orchestrator runs real pytest and feeds failures back."""
    buggy = "def add(a, b):\n    return a - b\n"
    fixed = "def add(a, b):\n    return a + b\n"
    test = "from calc import add\n\ndef test_add():\n    assert add(2, 3) == 5\n"
    fake_claude.set_scenario({
        "session_id": SID,
        "calls": [{}, {"write": {"calc.py": buggy, "tests/test_calc.py": test, "tests/conftest.py":
                                 "import sys, os\nsys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))\n"}},
                  {"write": {"calc.py": fixed}}],
    })
    _, summary = await run_to_end(orchestrator, task(verification_commands=None))
    argvs = fake_claude.argvs()
    assert_single_session(argvs)
    heal = argvs[2][argvs[2].index("-p") + 1]
    assert "assert -1 == 5" in heal or "AssertionError" in heal
    assert summary.status == TaskStatus.COMPLETED
    assert summary.verification.results[0].command.endswith("-m pytest -q")


async def test_no_verification_suite_never_completes(orchestrator, fake_claude):
    fake_claude.set_scenario({"session_id": SID, "default": {}})
    _, summary = await run_to_end(orchestrator, task(verification_commands=None, max_turns=3))
    assert summary.status == TaskStatus.FAILED
    heal = fake_claude.argvs()[2][fake_claude.argvs()[2].index("-p") + 1]
    assert "no verification suite found" in heal


async def test_events_are_recorded_in_order(orchestrator, fake_claude, registry):
    fake_claude.set_scenario({"session_id": SID, "calls": [{}, {"write": {"status.txt": "pass"}}]})
    state, _ = await run_to_end(orchestrator, task())
    events = await registry.events(state.task_id)
    assert [e.seq for e in events] == list(range(1, len(events) + 1))
    statuses = [e.status for e in events if e.type == "status"]
    assert statuses == [TaskStatus.HYDRATING, TaskStatus.PLANNING, TaskStatus.IMPLEMENTING, TaskStatus.VERIFYING]
    assert events[-1].type == "completed"


async def test_live_output_streamed_to_subscribers(orchestrator, fake_claude):
    fake_claude.set_scenario({"session_id": SID, "calls": [{"preamble": "thinking hard"}, {"write": {"status.txt": "pass"}}]})
    state = await orchestrator.submit(task(), start=False)
    q = orchestrator.bus.subscribe(state.task_id)
    await orchestrator.run(state.task_id)
    seen = []
    while not q.empty():
        seen.append(q.get_nowait())
    assert any(e.type == "output" and e.message == "thinking hard" for e in seen)
    assert seen[-1].type == "completed"


async def test_repo_url_is_cloned_into_empty_workspace(orchestrator, fake_claude, tmp_path):
    import subprocess
    src = tmp_path / "upstream"
    src.mkdir()
    (src / "README.md").write_text("hello")
    for cmd in (["git", "init", "-q"], ["git", "add", "."],
                ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init"]):
        subprocess.run(cmd, cwd=src, check=True)
    fake_claude.set_scenario({"session_id": SID, "calls": [{}, {"write": {"status.txt": "pass"}}]})
    state, summary = await run_to_end(orchestrator, task(repo_url=str(src)))
    assert (Path(state.workspace_path) / "README.md").read_text() == "hello"
    assert summary.status == TaskStatus.COMPLETED


async def test_bad_repo_url_fails(orchestrator, fake_claude, tmp_path):
    _, summary = await run_to_end(orchestrator, task(repo_url=str(tmp_path / "nope")))
    assert summary.status == TaskStatus.FAILED and "git clone failed" in summary.failure_reason
    assert fake_claude.argvs() == []
