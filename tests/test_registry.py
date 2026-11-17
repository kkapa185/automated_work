from __future__ import annotations

import uuid

import pytest

from registry import DuplicateTaskError, SessionInvariantError, SessionRegistry, TaskNotFoundError
from schemas import FinalSummary, SessionState, TaskEvent, TaskInput, TaskStatus, TokenUsage, TurnRecord


def make_state(ws: str = "/tmp/ws") -> SessionState:
    return SessionState(task_id=str(uuid.uuid4()), workspace_path=ws, task_input=TaskInput(description="d"))


def turn(task_id: str, idx: int, sid: str = "s1", tokens: int = 10, cost: float = 0.1) -> TurnRecord:
    return TurnRecord(task_id=task_id, turn_index=idx, phase=TaskStatus.PLANNING, session_id=sid, resumed=idx > 1,
                      prompt="p", response="r", usage=TokenUsage(input_tokens=tokens), cost_usd=cost)


async def test_create_and_get(registry):
    st = await registry.create_task(make_state())
    got = await registry.get(st.task_id)
    assert got.task_id == st.task_id and got.status == TaskStatus.PENDING and got.session_id is None
    assert got.task_input.description == "d"
    assert await registry.exists(st.task_id)
    assert not await registry.exists("nope")


async def test_duplicate_task_rejected(registry):
    st = await registry.create_task(make_state())
    with pytest.raises(DuplicateTaskError):
        await registry.create_task(st)


async def test_unknown_task(registry):
    with pytest.raises(TaskNotFoundError):
        await registry.get("missing")
    with pytest.raises(TaskNotFoundError):
        await registry.update_status("missing", TaskStatus.FAILED)


async def test_bind_session_once(registry):
    st = await registry.create_task(make_state())
    await registry.bind_session(st.task_id, "s1")
    await registry.bind_session(st.task_id, "s1")  # idempotent
    with pytest.raises(SessionInvariantError):
        await registry.bind_session(st.task_id, "s2")
    assert (await registry.get(st.task_id)).session_id == "s1"


async def test_session_cannot_belong_to_two_tasks(registry):
    a = await registry.create_task(make_state())
    b = await registry.create_task(make_state())
    await registry.bind_session(a.task_id, "shared")
    with pytest.raises(SessionInvariantError):
        await registry.bind_session(b.task_id, "shared")


async def test_record_turn_accumulates(registry):
    st = await registry.create_task(make_state())
    await registry.bind_session(st.task_id, "s1")
    await registry.record_turn(turn(st.task_id, 1))
    s = await registry.record_turn(turn(st.task_id, 2, tokens=5, cost=0.25))
    assert s.turn_count == 2 and s.token_usage.input_tokens == 15 and s.total_cost_usd == pytest.approx(0.35)
    assert [t.turn_index for t in await registry.turns(st.task_id)] == [1, 2]


async def test_record_turn_wrong_session_rejected(registry):
    st = await registry.create_task(make_state())
    await registry.bind_session(st.task_id, "s1")
    with pytest.raises(SessionInvariantError):
        await registry.record_turn(turn(st.task_id, 1, sid="s2"))
    assert (await registry.get(st.task_id)).turn_count == 0


async def test_duplicate_turn_index_rolls_back(registry):
    st = await registry.create_task(make_state())
    await registry.bind_session(st.task_id, "s1")
    await registry.record_turn(turn(st.task_id, 1))
    with pytest.raises(Exception):
        await registry.record_turn(turn(st.task_id, 1))
    assert (await registry.get(st.task_id)).turn_count == 1


async def test_persistence_and_resumable(tmp_path):
    db = tmp_path / "x.db"
    r1 = SessionRegistry(db)
    done = await r1.create_task(make_state())
    live = await r1.create_task(make_state())
    await r1.bind_session(live.task_id, "s-live")
    await r1.update_status(done.task_id, TaskStatus.COMPLETED)
    await r1.update_status(live.task_id, TaskStatus.HEALING, last_error="boom")
    r1.close()
    r2 = SessionRegistry(db)
    resumable = await r2.list_resumable()
    assert [s.task_id for s in resumable] == [live.task_id]
    assert resumable[0].session_id == "s-live" and resumable[0].last_error == "boom"
    assert len(await r2.list()) == 2
    assert [s.task_id for s in await r2.list(status=TaskStatus.COMPLETED)] == [done.task_id]
    r2.close()


async def test_events_sequence(registry):
    st = await registry.create_task(make_state())
    for i in range(3):
        await registry.add_event(TaskEvent(task_id=st.task_id, type="status", message=str(i)))
    evs = await registry.events(st.task_id)
    assert [e.seq for e in evs] == [1, 2, 3]
    assert [e.message for e in await registry.events(st.task_id, after_seq=2)] == ["2"]


async def test_summary_roundtrip(registry):
    st = await registry.create_task(make_state())
    assert await registry.get_summary(st.task_id) is None
    s = FinalSummary(task_id=st.task_id, session_id=None, status=TaskStatus.FAILED, turns_used=0, max_turns=5,
                     token_usage=TokenUsage(), total_cost_usd=0, verification=None, final_message=None,
                     workspace_path="/tmp/ws")
    await registry.set_summary(s)
    assert (await registry.get_summary(st.task_id)).status == TaskStatus.FAILED
