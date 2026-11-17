"""Milestone mode: large builds are implemented, verified and healed milestone by milestone."""
from __future__ import annotations

import json

from claude_session import ClaudeSessionManager
from orchestrator import TaskOrchestrator, load_milestones
from registry import SessionRegistry
from schemas import TaskInput, TaskStatus

from tests.conftest import check_cmd

SID = "sess-abc"
MS = {"milestones": [{"id": "M1", "title": "core", "criteria": ["R1"]},
                     {"id": "M2", "title": "features", "criteria": ["R2", "R3"]},
                     {"id": "M3", "title": "hardening", "criteria": ["R4"]}]}
PLAN_WITH_MS = {"write": {".orchestrator/milestones.json": json.dumps(MS)}, "result": "plan"}


def task(**kw):
    kw.setdefault("description", "build a big thing")
    kw.setdefault("verification_commands", [check_cmd()])
    kw.setdefault("auto_detect_sources", False)
    return TaskInput(**kw)


def prompts(fake):
    return [a[a.index("-p") + 1] for a in fake.argvs()]


def test_load_milestones_variants(tmp_path):
    assert load_milestones(str(tmp_path)) == []
    d = tmp_path / ".orchestrator"
    d.mkdir()
    (d / "milestones.json").write_text("{not json")
    assert load_milestones(str(tmp_path)) == []
    (d / "milestones.json").write_text(json.dumps([{"id": "A", "title": "x"}, {"id": "A"}, "plain title"]))
    ms = load_milestones(str(tmp_path))
    assert [m.id for m in ms] == ["A", "A-2", "M3"] and ms[2].title == "plain title"
    (d / "milestones.json").write_text(json.dumps({"milestones": [{"id": f"M{i}"} for i in range(30)]}))
    assert len(load_milestones(str(tmp_path))) == 12


async def test_milestones_drive_one_implement_turn_each(orchestrator, fake_claude, registry):
    fake_claude.set_scenario({"session_id": SID, "calls": [
        PLAN_WITH_MS,
        {"write": {"status.txt": "pass"}},  # M1
        {"write": {"status.txt": "pass"}},  # M2
        {"write": {"status.txt": "pass"}},  # M3
    ]})
    st = await orchestrator.submit(task())
    summary = await orchestrator.wait(st.task_id, timeout=60)
    turns = await registry.turns(st.task_id)
    assert [(t.phase, t.milestone) for t in turns] == [
        (TaskStatus.PLANNING, None), (TaskStatus.IMPLEMENTING, "M1"), (TaskStatus.IMPLEMENTING, "M2"),
        (TaskStatus.IMPLEMENTING, "M3")]
    ps = prompts(fake_claude)
    assert "Milestone 1 of 3: M1 core" in ps[1] and "R2, R3" in ps[2] and "Milestone 3 of 3" in ps[3]
    assert summary.status == TaskStatus.COMPLETED
    assert {a[a.index("--resume") + 1] for a in fake_claude.argvs()[1:]} == {SID}
    evs = [e.type for e in await registry.events(st.task_id)]
    assert "milestones" in evs and evs.count("milestone") == 3


async def test_failing_milestone_is_healed_before_the_next(orchestrator, fake_claude, registry):
    fake_claude.set_scenario({"session_id": SID, "calls": [
        PLAN_WITH_MS,
        {"write": {"status.txt": "broken"}},      # M1 fails
        {"write": {"status.txt": "pass"}},        # heal M1
        {"write": {"status.txt": "pass"}},        # M2
        {"write": {"status.txt": "pass"}},        # M3
    ]})
    st = await orchestrator.submit(task())
    summary = await orchestrator.wait(st.task_id, timeout=60)
    turns = await registry.turns(st.task_id)
    assert [(t.phase.value, t.milestone) for t in turns][1:4] == [
        ("IMPLEMENTING", "M1"), ("HEALING", "M1"), ("IMPLEMENTING", "M2")]
    assert summary.status == TaskStatus.COMPLETED


async def test_milestone_heal_budget_then_moves_on(settings, registry, sleeps, fake_claude):
    s = settings.model_copy(update={"milestone_heal_turns": 1})
    orch = TaskOrchestrator(s, registry, sessions=ClaudeSessionManager(s, registry, sleep=sleeps))
    fake_claude.set_scenario({"session_id": SID, "calls": [
        PLAN_WITH_MS, {"write": {"status.txt": "x"}}, {"write": {"status.txt": "pass"}}, {"write": {"status.txt": "pass"}}]})
    st = await orch.submit(task())
    await orch.wait(st.task_id, timeout=60)
    turns = await registry.turns(st.task_id)
    # with a heal budget of 1 verification attempt, M1 failing does not block M2/M3
    assert [t.milestone for t in turns if t.phase == TaskStatus.IMPLEMENTING] == ["M1", "M2", "M3"]


async def test_turn_budget_scales_with_milestones_and_is_capped(settings, registry, sleeps, fake_claude):
    s = settings.model_copy(update={"turns_per_milestone": 3, "max_turns_cap": 9})
    orch = TaskOrchestrator(s, registry, sessions=ClaudeSessionManager(s, registry, sleep=sleeps))
    fake_claude.set_scenario({"session_id": SID, "calls": [PLAN_WITH_MS], "default": {"write": {"status.txt": "x"}}})
    st = await orch.submit(task(max_turns=4))
    summary = await orch.wait(st.task_id, timeout=60)
    assert summary.status == TaskStatus.FAILED and summary.turns_used == 9  # 4 + 3*3 = 13, capped at 9
    assert summary.max_turns == 9  # the effective (scaled, capped) budget is reported


async def test_resume_continues_at_the_next_milestone(settings, sleeps, fake_claude):
    fake_claude.set_scenario({"session_id": SID, "calls": [PLAN_WITH_MS, {"write": {"status.txt": "pass"}}],
                              "default": {"write": {"status.txt": "pass"}}})
    reg1 = SessionRegistry(settings.db_path)
    orch1 = TaskOrchestrator(settings, reg1, sessions=ClaudeSessionManager(settings, reg1, sleep=sleeps))
    st = await orch1.submit(task(), start=False)
    await orch1.sessions.send(st.task_id, "plan", TaskStatus.PLANNING)
    await orch1.sessions.send(st.task_id, "m1", TaskStatus.IMPLEMENTING, milestone="M1")
    reg1.close()
    reg2 = SessionRegistry(settings.db_path)
    orch2 = TaskOrchestrator(settings, reg2, sessions=ClaudeSessionManager(settings, reg2, sleep=sleeps))
    await orch2.resume_interrupted()
    summary = await orch2.wait(st.task_id, timeout=60)
    turns = await reg2.turns(st.task_id)
    reg2.close()
    assert [t.milestone for t in turns if t.phase == TaskStatus.IMPLEMENTING] == ["M1", "M2", "M3"]
    assert summary.status == TaskStatus.COMPLETED
    assert all(a[0:2] == ["--resume", SID] for a in fake_claude.argvs()[1:])


async def test_small_task_without_milestones_keeps_single_implement(orchestrator, fake_claude, registry):
    fake_claude.set_scenario({"session_id": SID, "calls": [{}, {"write": {"status.txt": "pass"}}]})
    st = await orchestrator.submit(task())
    await orchestrator.wait(st.task_id, timeout=60)
    turns = await registry.turns(st.task_id)
    assert [(t.phase, t.milestone) for t in turns] == [(TaskStatus.PLANNING, None), (TaskStatus.IMPLEMENTING, None)]


def test_plan_prompt_offers_milestones():
    from prompts import plan_prompt
    p = plan_prompt("<c/>", None, "/w")
    assert ".orchestrator/milestones.json" in p and "2-8 ordered milestones" in p
