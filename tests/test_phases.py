"""Usage-limit pauses, requirement reviews, constraints and permission-denial feedback."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from claude_session import ClaudeSessionManager
from orchestrator import TaskOrchestrator
from registry import SessionRegistry
from schemas import TaskInput, TaskStatus
from usage_limits import UsageGate

from tests.conftest import check_cmd
from tests.test_usage_limits import FakeClock

SID = "sess-abc"
START = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)
LIMIT_5H = {"is_error": True, "exit_code": 1, "result": "You've hit your session limit · resets 3pm (UTC)"}
LIMIT_WEEK = {"is_error": True, "exit_code": 1, "result": "You've hit your weekly limit · resets Mon 9am (UTC)"}
PASS = {"write": {"status.txt": "pass"}}


def task(**kw) -> TaskInput:
    kw.setdefault("description", "make the check pass")
    kw.setdefault("verification_commands", [check_cmd()])
    kw.setdefault("auto_detect_sources", False)
    return TaskInput(**kw)


def make(settings, registry, sleeps, clk: FakeClock | None = None, **overrides):
    s = settings.model_copy(update=overrides) if overrides else settings
    clk = clk or FakeClock(START)
    gate = UsageGate(clock=clk.now, sleep=clk.sleep, poll_s=60)
    orch = TaskOrchestrator(s, registry, sessions=ClaudeSessionManager(s, registry, sleep=sleeps), gate=gate, clock=clk.now)
    return orch, clk


def prompts(fake) -> list[str]:
    return [a[a.index("-p") + 1] for a in fake.argvs()]


async def run(orch, t):
    st = await orch.submit(t)
    return st, await orch.wait(st.task_id, timeout=60)


# ------------------------------------------------------------------ usage limits

async def test_five_hour_limit_pauses_until_reset_then_resumes_same_session(settings, registry, sleeps, fake_claude):
    fake_claude.set_scenario({"session_id": SID, "calls": [{}, LIMIT_5H, PASS]})
    orch, clk = make(settings, registry, sleeps)
    st, summary = await run(orch, task())
    argvs = fake_claude.argvs()
    assert len(argvs) == 3
    assert argvs[1][0:2] == ["--resume", SID] and argvs[2][0:2] == ["--resume", SID]
    assert prompts(fake_claude)[1] == prompts(fake_claude)[2]  # the same turn is re-sent
    assert summary.status == TaskStatus.COMPLETED and summary.turns_used == 2  # pause consumed no turn
    assert clk.slept == timedelta(hours=3, minutes=2).total_seconds()  # 3pm reset + 2 min margin
    assert sleeps.delays == []  # not treated as a transient error
    events = await registry.events(st.task_id)
    paused = [e for e in events if e.type == "paused"]
    assert len(paused) == 1 and paused[0].data["resume_at"] == "2026-11-17T15:02:00+00:00"
    assert paused[0].data["phase"] == "IMPLEMENTING"
    assert any(e.type == "resumed" and e.data.get("waited_s") is not None for e in events)
    final = await registry.get(st.task_id)
    assert final.resume_at is None and final.paused_phase is None


async def test_weekly_limit_on_first_call_waits_days(settings, registry, sleeps, fake_claude):
    fake_claude.set_scenario({"session_id": SID, "calls": [{"raw_stdout": "", "exit_code": 1,
                                                            "stderr": LIMIT_WEEK["result"]}, {}, PASS]})
    orch, clk = make(settings, registry, sleeps)
    _, summary = await run(orch, task())
    argvs = fake_claude.argvs()
    assert "--resume" not in argvs[0] and "--resume" not in argvs[1]  # no session existed yet
    assert argvs[2][0:2] == ["--resume", SID]
    assert summary.status == TaskStatus.COMPLETED
    assert clk.t == datetime(2026, 11, 23, 9, 2, tzinfo=timezone.utc)


async def test_unknown_reset_uses_probe_schedule(settings, registry, sleeps, fake_claude):
    out = {"is_error": True, "exit_code": 1, "result": "You're out of usage credits"}
    fake_claude.set_scenario({"session_id": SID, "calls": [{}, out, out, out, PASS]})
    orch, clk = make(settings, registry, sleeps, usage_probe_schedule_s=[600.0, 1200.0])
    _, summary = await run(orch, task())
    assert summary.status == TaskStatus.COMPLETED
    assert clk.slept == 600 + 1200 + 1200


async def test_limit_blocks_all_tasks_via_shared_gate(settings, registry, sleeps, fake_claude):
    """Once one task is paused, another task does not call claude until the reset."""
    fake_claude.set_scenario({"session_id": SID, "calls": [LIMIT_5H], "default": PASS})
    orch, clk = make(settings, registry, sleeps)
    a = await orch.submit(task(), start=False)
    await orch.run(a.task_id)
    calls_before = len(fake_claude.argvs())
    orch.gate.block(clk.now() + timedelta(hours=1))
    b = await orch.submit(task(), start=False)
    t0 = clk.now()
    await orch.run(b.task_id)
    assert clk.now() - t0 >= timedelta(hours=1)
    assert len(fake_claude.argvs()) > calls_before
    evs = await registry.events(b.task_id)
    assert any(e.type == "paused" and "another task" in e.data["reason"] for e in evs)


async def test_restart_during_pause_honours_persisted_resume_at(settings, sleeps, fake_claude):
    fake_claude.set_scenario({"session_id": SID, "calls": [{}, {}], "default": PASS})
    reg1 = SessionRegistry(settings.db_path)
    orch1, _ = make(settings, reg1, sleeps)
    st = await orch1.submit(task(), start=False)
    await orch1.sessions.send(st.task_id, "plan", TaskStatus.PLANNING)
    await orch1.sessions.send(st.task_id, "impl", TaskStatus.IMPLEMENTING)
    resume_at = START + timedelta(hours=4)
    await reg1.set_pause(st.task_id, resume_at, TaskStatus.HEALING, "You've hit your session limit")
    reg1.close()

    reg2 = SessionRegistry(settings.db_path)
    paused = await reg2.get(st.task_id)
    assert paused.status == TaskStatus.PAUSED_USAGE_LIMIT and paused.resume_at == resume_at
    assert paused.paused_phase == TaskStatus.HEALING
    orch2, clk = make(settings, reg2, sleeps)
    assert await orch2.resume_interrupted() == [st.task_id]
    summary = await orch2.wait(st.task_id, timeout=60)
    reg2.close()
    # verification ran on the existing workspace, failed, and the heal turn waited for the reset first
    assert clk.now() >= resume_at
    assert summary.status == TaskStatus.COMPLETED and summary.session_id == SID
    assert all(a[0:2] == ["--resume", SID] for a in fake_claude.argvs()[2:])


# ------------------------------------------------------------------ review phase

async def test_review_pass_completes(settings, registry, sleeps, fake_claude):
    fake_claude.set_scenario({"session_id": SID, "calls": [{}, PASS, {"result": "all good\nREVIEW_VERDICT: PASS"}]})
    orch, _ = make(settings, registry, sleeps, max_reviews=2)
    st, summary = await run(orch, task())
    assert summary.status == TaskStatus.COMPLETED and summary.review_verdict == "PASS"
    assert summary.turns_used == 3
    assert "Final review against the requirements" in prompts(fake_claude)[2]
    assert [t.phase for t in await registry.turns(st.task_id)][-1] == TaskStatus.REVIEWING


async def test_review_gaps_fixed_triggers_second_review(settings, registry, sleeps, fake_claude):
    fake_claude.set_scenario({"session_id": SID, "calls": [
        {}, PASS, {"result": "added X\nREVIEW_VERDICT: GAPS_FIXED"}, {"result": "REVIEW_VERDICT: PASS"}]})
    orch, _ = make(settings, registry, sleeps, max_reviews=3)
    _, summary = await run(orch, task())
    assert summary.turns_used == 4 and summary.review_verdict == "PASS"


async def test_review_that_breaks_tests_is_healed(settings, registry, sleeps, fake_claude):
    fake_claude.set_scenario({"session_id": SID, "calls": [
        {}, PASS, {"write": {"status.txt": "broken"}, "result": "REVIEW_VERDICT: GAPS_FIXED"},
        PASS, {"result": "REVIEW_VERDICT: PASS"}]})
    orch, _ = make(settings, registry, sleeps, max_reviews=3)
    st, summary = await run(orch, task())
    phases = [t.phase for t in await registry.turns(st.task_id)]
    assert phases == [TaskStatus.PLANNING, TaskStatus.IMPLEMENTING, TaskStatus.REVIEWING, TaskStatus.HEALING,
                      TaskStatus.REVIEWING]
    assert summary.status == TaskStatus.COMPLETED


async def test_review_limited_by_max_reviews_and_budget(settings, registry, sleeps, fake_claude):
    fake_claude.set_scenario({"session_id": SID, "calls": [{}, PASS], "default": {"result": "REVIEW_VERDICT: GAPS_FIXED"}})
    orch, _ = make(settings, registry, sleeps, max_reviews=2)
    _, summary = await run(orch, task())
    assert summary.turns_used == 4 and summary.status == TaskStatus.COMPLETED
    assert summary.review_verdict == "GAPS_FIXED"
    fake_claude.log_path.unlink()
    fake_claude.set_scenario({"session_id": "s2", "calls": [{}, PASS]})
    orch2, _ = make(settings, registry, sleeps, max_reviews=5)
    _, s2 = await run(orch2, task(max_turns=2))
    assert s2.turns_used == 2 and s2.review_verdict == "SKIPPED_BUDGET" and s2.status == TaskStatus.COMPLETED


# ------------------------------------------------------------------ prompts

async def test_constraints_and_denials_reach_prompts(settings, registry, sleeps, fake_claude):
    fake_claude.set_scenario({"session_id": SID, "calls": [
        {}, {"write": {"status.txt": "x"}}, PASS]})
    # Inject a permission denial into the implement turn's JSON output.
    import json
    scen = json.loads(fake_claude.scenario_path.read_text())
    fake_claude.set_scenario(scen)
    orch, _ = make(settings, registry, sleeps)
    real_send = orch.sessions.send

    async def send(task_id, prompt, phase, on_line=None):
        out = await real_send(task_id, prompt, phase, on_line=on_line)
        if phase == TaskStatus.IMPLEMENTING:
            out.turn.permission_denials.append({"tool_name": "WebFetch", "tool_input": {"url": "https://x"}})
        return out

    orch.sessions.send = send  # type: ignore[method-assign]
    _, summary = await run(orch, task(constraints=["Do not access github.com/acme/reference"]))
    ps = prompts(fake_claude)
    assert all("Do not access github.com/acme/reference" in p for p in ps)
    assert "DENIED" in ps[2] and "WebFetch" in ps[2] and "DENIED" not in ps[1]
    assert summary.status == TaskStatus.COMPLETED


async def test_plan_prompt_requires_requirements_and_contract(settings, registry, sleeps, fake_claude):
    fake_claude.set_scenario({"session_id": SID, "calls": [{}, PASS]})
    orch, _ = make(settings, registry, sleeps)
    await run(orch, task(verification_commands=None, max_turns=2))
    plan, impl = prompts(fake_claude)[:2]
    assert ".orchestrator/requirements.md" in plan and "acceptance criteria" in plan
    assert ".orchestrator/verify.json" in impl
