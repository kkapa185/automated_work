from __future__ import annotations

import json
import time

import pytest
from fastapi.testclient import TestClient

from main import build_parser, create_app, main
from schemas import TaskStatus

from tests.conftest import check_cmd

SID = "sess-abc"


@pytest.fixture
def api(settings, orchestrator):
    app = create_app(settings, orchestrator=orchestrator)
    with TestClient(app) as c:
        yield c


def wait_terminal(c: TestClient, tid: str, timeout: float = 30) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = c.get(f"/tasks/{tid}").json()
        if TaskStatus(body["status"]).is_terminal:
            return body
        time.sleep(0.05)
    raise AssertionError("task did not finish")


def payload(**kw):
    body = {"description": "make status pass", "verification_commands": [check_cmd()], "auto_detect_sources": False}
    body.update(kw)
    return body


def test_health(api):
    body = api.get("/healthz").json()
    assert body["status"] == "ok" and body["usage_gate"]["blocked"] is False


def test_submit_complete_and_inspect(api, fake_claude):
    fake_claude.set_scenario({"session_id": SID, "calls": [{}, {"write": {"status.txt": "fail"}}, {"write": {"status.txt": "pass"}}]})
    r = api.post("/tasks", json=payload())
    assert r.status_code == 202
    tid = r.json()["task_id"]
    state = wait_terminal(api, tid)
    assert state["status"] == "COMPLETED" and state["session_id"] == SID and state["turn_count"] == 3

    turns = api.get(f"/tasks/{tid}/turns").json()
    assert [t["session_id"] for t in turns] == [SID] * 3 and [t["resumed"] for t in turns] == [False, True, True]
    summary = api.get(f"/tasks/{tid}/summary").json()
    assert summary["status"] == "COMPLETED" and summary["verification"]["passed"]
    assert any(t["task_id"] == tid for t in api.get("/tasks").json())
    assert api.get("/tasks", params={"status": "FAILED"}).json() == []

    with api.stream("GET", f"/tasks/{tid}/events") as resp:
        assert resp.headers["content-type"].startswith("text/event-stream")
        text = "".join(resp.iter_text())
    events = [json.loads(line[6:]) for line in text.splitlines() if line.startswith("data: ")]
    assert events[0]["type"] == "submitted" and events[-1]["type"] == "completed"
    assert "event: verification" in text and "id: 1" in text
    with api.stream("GET", f"/tasks/{tid}/events", params={"after": len(events) - 1}) as resp:
        after = "".join(resp.iter_text())
    assert after.count("data: ") == 1


def test_validation_errors(api):
    assert api.post("/tasks", json={"description": ""}).status_code == 422
    assert api.post("/tasks", json=payload(max_turns=1)).status_code == 422
    assert api.post("/tasks", json=payload(safety="yolo")).status_code == 422
    assert api.post("/tasks", params={"task_id": "bad"}, json=payload()).status_code == 422


def test_duplicate_task_id_conflict(api, fake_claude):
    import uuid
    fake_claude.set_scenario({"session_id": SID, "calls": [{}, {"write": {"status.txt": "pass"}}]})
    tid = str(uuid.uuid4())
    assert api.post("/tasks", params={"task_id": tid}, json=payload()).status_code == 202
    assert api.post("/tasks", params={"task_id": tid}, json=payload()).status_code == 409
    wait_terminal(api, tid)


def test_not_found(api):
    for path in ("/tasks/x", "/tasks/x/turns", "/tasks/x/summary", "/tasks/x/events"):
        assert api.get(path).status_code == 404
    assert api.post("/tasks/x/cancel").status_code == 404
    assert api.post("/tasks/x/resume").status_code == 404


def test_summary_before_finish_conflict_and_cancel(api, fake_claude):
    fake_claude.set_scenario({"session_id": SID, "default": {"sleep": 30}})
    tid = api.post("/tasks", json=payload()).json()["task_id"]
    time.sleep(0.3)
    assert api.get(f"/tasks/{tid}/summary").status_code == 409
    r = api.post(f"/tasks/{tid}/cancel")
    assert r.status_code == 200 and r.json()["status"] == "CANCELLED"
    assert api.get(f"/tasks/{tid}").json()["status"] == "CANCELLED"
    assert api.post(f"/tasks/{tid}/cancel").status_code == 409
    assert api.post(f"/tasks/{tid}/resume").status_code == 409


def test_failed_task_summary(api, fake_claude):
    fake_claude.set_scenario({"session_id": SID, "default": {}})
    tid = api.post("/tasks", json=payload(max_turns=2)).json()["task_id"]
    assert wait_terminal(api, tid)["status"] == "FAILED"
    s = api.get(f"/tasks/{tid}/summary").json()
    assert s["failure_reason"].startswith("max_turns_exhausted") and s["turns_used"] == 2


def test_startup_resumes_interrupted_tasks(settings, orchestrator, registry, fake_claude):
    import asyncio
    from schemas import SessionState, TaskInput

    fake_claude.set_scenario({"session_id": SID, "default": {"write": {"status.txt": "pass"}}})
    ws = settings.workspace_root / "w"
    ws.mkdir(parents=True)
    st = SessionState(task_id="11111111-1111-4111-8111-111111111111", workspace_path=str(ws), status=TaskStatus.HEALING,
                      turn_count=0, task_input=TaskInput(description="d", verification_commands=[check_cmd()]))
    asyncio.run(registry.create_task(st))
    asyncio.run(registry.bind_session(st.task_id, "sess-crashed"))
    with TestClient(create_app(settings, orchestrator=orchestrator)) as c:
        body = wait_terminal(c, st.task_id)
    assert body["status"] == "COMPLETED" and body["session_id"] == "sess-crashed"
    assert all(a[0:2] == ["--resume", "sess-crashed"] for a in fake_claude.argvs())


def test_cli_run_and_status(settings, fake_claude, monkeypatch, capsys, tmp_path):
    import config
    monkeypatch.setattr(config, "get_settings", lambda: settings)
    import main as main_mod
    monkeypatch.setattr(main_mod, "get_settings", lambda: settings)
    fake_claude.set_scenario({"session_id": SID, "calls": [{}, {"write": {"status.txt": "pass"}}]})
    ws = tmp_path / "cli-ws"
    code = main(["run", "make it pass", "--workspace", str(ws), "--verify", check_cmd(), "--no-detect",
                 "--source", "text:extra notes"])
    out = capsys.readouterr().out
    assert code == 0
    summary = json.loads(out[out.index("{"):])
    assert summary["status"] == "COMPLETED" and summary["session_id"] == SID
    tid = summary["task_id"]
    assert main(["status", tid, "--turns"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["state"]["status"] == "COMPLETED" and len(status["turns"]) == 2
    assert main(["list"]) == 0 and tid in capsys.readouterr().out
    assert main(["status", "missing"]) == 2

    fake_claude.set_scenario({"session_id": SID, "default": {}})
    assert main(["run", "never passes", "--workspace", str(tmp_path / "w2"), "--verify", check_cmd(),
                 "--no-detect", "--max-turns", "2"]) == 1


def test_parser():
    args = build_parser().parse_args(["run", "x", "--verify", "a", "--verify", "b", "--safety", "read_only"])
    assert args.verify == ["a", "b"] and args.safety == "read_only"
