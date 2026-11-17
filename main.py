"""FastAPI server and command-line entrypoint for the Task Orchestrator.

    python main.py serve --host 0.0.0.0 --port 8000
    python main.py run "Implement PROJ-123" --workspace ./repo --verify "pytest -q"
    python main.py status <task_id>
    python main.py list

Or serve with uvicorn directly: ``uvicorn main:create_app --factory``.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import sys
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from config import Settings, get_settings
from orchestrator import TERMINAL_EVENT_TYPES, TaskOrchestrator
from registry import DuplicateTaskError, SessionRegistry, TaskNotFoundError
from schemas import (
    ContextSource, FinalSummary, SafetyLevel, SessionState, TaskCreated, TaskEvent, TaskInput, TaskStatus, TurnRecord,
)

log = logging.getLogger("orchestrator")


def build_orchestrator(settings: Settings) -> TaskOrchestrator:
    settings.workspace_root.mkdir(parents=True, exist_ok=True)
    return TaskOrchestrator(settings, SessionRegistry(settings.db_path))


def create_app(settings: Settings | None = None, orchestrator: TaskOrchestrator | None = None,
               resume_on_startup: bool = True) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        orch = orchestrator or build_orchestrator(settings)
        app.state.orchestrator = orch
        if resume_on_startup:
            resumed = await orch.resume_interrupted()
            if resumed:
                log.info("resumed %d interrupted task(s)", len(resumed))
        try:
            yield
        finally:
            await orch.shutdown()

    app = FastAPI(title="Claude Task Orchestrator", version="1.0.0", lifespan=lifespan)

    def orch(request: Request) -> TaskOrchestrator:
        return request.app.state.orchestrator

    async def get_state(o: TaskOrchestrator, task_id: str) -> SessionState:
        try:
            return await o.registry.get(task_id)
        except TaskNotFoundError:
            raise HTTPException(404, f"task {task_id} not found") from None

    @app.get("/healthz")
    async def healthz(request: Request) -> dict[str, Any]:
        gate = orch(request).gate
        return {
            "status": "ok",
            "usage_gate": {
                "blocked": gate.is_blocked,
                "blocked_until": gate.blocked_until.isoformat() if gate.blocked_until else None,
                "limit_kind": gate.info.kind if gate.info else None,
            },
        }

    @app.post("/tasks", status_code=202, response_model=TaskCreated)
    async def submit_task(task: TaskInput, request: Request, task_id: str | None = Query(default=None)) -> TaskCreated:
        o = orch(request)
        try:
            state = await o.submit(task, task_id=task_id)
        except DuplicateTaskError as exc:
            raise HTTPException(409, str(exc)) from None
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        return TaskCreated(task_id=state.task_id, status=state.status, workspace_path=state.workspace_path)

    @app.get("/tasks", response_model=list[SessionState])
    async def list_tasks(request: Request, status: TaskStatus | None = None,
                         limit: int = Query(100, ge=1, le=1000)) -> list[SessionState]:
        return await orch(request).registry.list(limit=limit, status=status)

    @app.get("/tasks/{task_id}", response_model=SessionState)
    async def get_task(task_id: str, request: Request) -> SessionState:
        return await get_state(orch(request), task_id)

    @app.get("/tasks/{task_id}/turns", response_model=list[TurnRecord])
    async def get_turns(task_id: str, request: Request) -> list[TurnRecord]:
        o = orch(request)
        await get_state(o, task_id)
        return await o.registry.turns(task_id)

    @app.get("/tasks/{task_id}/summary", response_model=FinalSummary)
    async def get_summary(task_id: str, request: Request) -> FinalSummary:
        o = orch(request)
        await get_state(o, task_id)
        summary = await o.registry.get_summary(task_id)
        if summary is None:
            raise HTTPException(409, "task has not finished yet")
        return summary

    @app.post("/tasks/{task_id}/cancel")
    async def cancel_task(task_id: str, request: Request) -> dict[str, Any]:
        o = orch(request)
        state = await get_state(o, task_id)
        if state.status.is_terminal:
            raise HTTPException(409, f"task already {state.status.value}")
        cancelled = await o.cancel(task_id)
        if not cancelled:
            await o._finish(task_id, TaskStatus.CANCELLED, None, None, "cancelled", state.task_input.max_turns or o.settings.max_turns)
        return {"task_id": task_id, "status": TaskStatus.CANCELLED.value}

    @app.post("/tasks/{task_id}/resume", status_code=202)
    async def resume_task(task_id: str, request: Request) -> dict[str, Any]:
        o = orch(request)
        state = await get_state(o, task_id)
        if state.status.is_terminal:
            raise HTTPException(409, f"task already {state.status.value}")
        o.start(task_id)
        return {"task_id": task_id, "session_id": state.session_id, "status": "resuming"}

    @app.get("/tasks/{task_id}/events")
    async def stream_events(task_id: str, request: Request, after: int = 0, include_output: bool = True) -> StreamingResponse:
        o = orch(request)
        await get_state(o, task_id)

        async def gen() -> AsyncIterator[str]:
            q = o.bus.subscribe(task_id)
            try:
                last = after
                for ev in await o.registry.events(task_id, after):
                    last = ev.seq
                    yield _sse(ev)
                    if ev.type in TERMINAL_EVENT_TYPES:
                        return
                state = await o.registry.get(task_id)
                if state.status.is_terminal and not o.is_running(task_id):
                    return
                while True:
                    if await request.is_disconnected():
                        return
                    try:
                        ev = await asyncio.wait_for(q.get(), timeout=15)
                    except asyncio.TimeoutError:
                        yield ": keep-alive\n\n"
                        continue
                    if ev.seq != -1 and ev.seq <= last:
                        continue
                    if ev.seq == -1 and not include_output:
                        continue
                    if ev.seq != -1:
                        last = ev.seq
                    yield _sse(ev)
                    if ev.type in TERMINAL_EVENT_TYPES:
                        return
            finally:
                o.bus.unsubscribe(task_id, q)

        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    return app


def _sse(ev: TaskEvent) -> str:
    lines = []
    if ev.seq > 0:
        lines.append(f"id: {ev.seq}")
    lines.append(f"event: {ev.type}")
    lines.append("data: " + ev.model_dump_json())
    return "\n".join(lines) + "\n\n"


# --------------------------------------------------------------------------- CLI


def _print_event(ev: TaskEvent, verbose: bool) -> None:
    if ev.type == "output":
        if verbose:
            print(f"    | {ev.message}", flush=True)
        return
    status = f"[{ev.status.value}]" if ev.status else ""
    print(f"{ev.created_at:%H:%M:%S} {ev.type:<12} {status:<14} {ev.message}", flush=True)


async def _cli_run(args: argparse.Namespace, settings: Settings) -> int:
    if args.description_file:
        from pathlib import Path
        args.description = Path(args.description_file).read_text()
    o = build_orchestrator(settings)
    sources = [ContextSource.model_validate({"kind": k, "ref": r}) for k, r in (s.split(":", 1) for s in args.source)]
    task = TaskInput(
        description=args.description, workspace_path=args.workspace, repo_url=args.repo,
        verification_commands=args.verify or None, max_turns=args.max_turns,
        safety=SafetyLevel(args.safety), allowed_tools=args.allowed_tools.split(",") if args.allowed_tools else None,
        context_sources=sources, auto_detect_sources=not args.no_detect, constraints=args.constraint,
    )
    state = await o.submit(task, task_id=args.task_id, start=False)
    print(f"task_id={state.task_id} workspace={state.workspace_path}", flush=True)
    q = o.bus.subscribe(state.task_id)
    runner = o.start(state.task_id)

    async def printer() -> None:
        while True:
            ev = await q.get()
            _print_event(ev, args.verbose)
            if ev.type in TERMINAL_EVENT_TYPES:
                return

    p = asyncio.create_task(printer())
    try:
        summary = await runner
    finally:
        with contextlib.suppress(asyncio.TimeoutError, asyncio.CancelledError):
            await asyncio.wait_for(p, timeout=2)
        p.cancel()
        o.registry.close()
    print(json.dumps(summary.model_dump(mode="json"), indent=2))
    return 0 if summary.status == TaskStatus.COMPLETED else 1


async def _cli_status(args: argparse.Namespace, settings: Settings) -> int:
    reg = SessionRegistry(settings.db_path)
    try:
        state = await reg.get(args.task_id)
    except TaskNotFoundError:
        print(f"task {args.task_id} not found", file=sys.stderr)
        return 2
    out: dict[str, Any] = {"state": state.model_dump(mode="json")}
    summary = await reg.get_summary(args.task_id)
    if summary:
        out["summary"] = summary.model_dump(mode="json")
    if args.turns:
        out["turns"] = [t.model_dump(mode="json") for t in await reg.turns(args.task_id)]
    print(json.dumps(out, indent=2))
    reg.close()
    return 0


async def _cli_list(args: argparse.Namespace, settings: Settings) -> int:
    reg = SessionRegistry(settings.db_path)
    for st in await reg.list(limit=args.limit):
        print(f"{st.task_id}  {st.status.value:<12} turns={st.turn_count:<3} session={st.session_id or '-'}  "
              f"{st.task_input.description[:60]!r}")
    reg.close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Autonomous Task Orchestrator driving the claude CLI")
    p.add_argument("--log-level", default="INFO")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("serve", help="run the HTTP API")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)
    s.add_argument("--no-resume", action="store_true", help="do not resume interrupted tasks on startup")

    r = sub.add_parser("run", help="run one task in the foreground")
    r.add_argument("description")
    r.add_argument("--workspace")
    r.add_argument("--repo")
    r.add_argument("--task-id")
    r.add_argument("--verify", action="append", default=[], help="verification command (repeatable)")
    r.add_argument("--source", action="append", default=[], help="explicit source kind:ref, e.g. jira:PROJ-1")
    r.add_argument("--max-turns", type=int)
    r.add_argument("--safety", choices=[x.value for x in SafetyLevel], default=SafetyLevel.STANDARD.value)
    r.add_argument("--allowed-tools", help="comma separated; requires --safety custom")
    r.add_argument("--no-detect", action="store_true", help="disable automatic source detection")
    r.add_argument("--constraint", action="append", default=[], help="extra rule injected into every prompt (repeatable)")
    r.add_argument("--description-file", help="read the task description from a file (use '-' as description)")
    r.add_argument("-v", "--verbose", action="store_true", help="stream raw claude output")

    st = sub.add_parser("status", help="show a task's state")
    st.add_argument("task_id")
    st.add_argument("--turns", action="store_true")

    ls = sub.add_parser("list", help="list tasks")
    ls.add_argument("--limit", type=int, default=50)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=args.log_level.upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = get_settings()
    if args.command == "serve":
        import uvicorn

        uvicorn.run(create_app(settings, resume_on_startup=not args.no_resume), host=args.host, port=args.port)
        return 0
    handler = {"run": _cli_run, "status": _cli_status, "list": _cli_list}[args.command]
    return asyncio.run(handler(args, settings))


if __name__ == "__main__":
    sys.exit(main())
