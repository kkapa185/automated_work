"""Task orchestrator: Hydrate -> Plan -> Implement -> Verify -> (Heal -> Verify)* on ONE claude session."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from pathlib import Path
from typing import Any

from claude_session import ClaudeError, ClaudeSessionManager, TurnOutcome
from config import Settings
from connectors import ContextHydrator
from process import run_process
from prompts import heal_prompt, implement_prompt, plan_prompt
from registry import DuplicateTaskError, SessionInvariantError, SessionRegistry
from schemas import (
    FinalSummary, SessionState, TaskEvent, TaskInput, TaskStatus, VerificationReport,
)
from verification import VerificationRunner

log = logging.getLogger(__name__)

TERMINAL_EVENT_TYPES = frozenset({"completed", "failed", "cancelled"})


class OrchestratorError(Exception):
    pass


class EventBus:
    """Persists task events and fans them out to live subscribers (SSE, CLI)."""

    def __init__(self, registry: SessionRegistry, queue_size: int = 1000):
        self.registry = registry
        self.queue_size = queue_size
        self._subs: dict[str, set[asyncio.Queue[TaskEvent]]] = {}

    def subscribe(self, task_id: str) -> asyncio.Queue[TaskEvent]:
        q: asyncio.Queue[TaskEvent] = asyncio.Queue(self.queue_size)
        self._subs.setdefault(task_id, set()).add(q)
        return q

    def unsubscribe(self, task_id: str, q: asyncio.Queue[TaskEvent]) -> None:
        subs = self._subs.get(task_id)
        if subs:
            subs.discard(q)
            if not subs:
                self._subs.pop(task_id, None)

    def _fanout(self, ev: TaskEvent) -> None:
        for q in list(self._subs.get(ev.task_id, ())):
            with contextlib.suppress(asyncio.QueueFull):
                q.put_nowait(ev)

    async def publish(self, task_id: str, type_: str, message: str = "", status: TaskStatus | None = None,
                      **data: Any) -> TaskEvent:
        ev = await self.registry.add_event(TaskEvent(task_id=task_id, type=type_, status=status, message=message, data=data))
        self._fanout(ev)
        return ev

    def publish_ephemeral(self, task_id: str, type_: str, message: str, **data: Any) -> None:
        """High-volume events (live CLI output) are streamed but not persisted."""
        self._fanout(TaskEvent(task_id=task_id, seq=-1, type=type_, message=message, data=data))


class TaskOrchestrator:
    def __init__(
        self,
        settings: Settings,
        registry: SessionRegistry,
        sessions: ClaudeSessionManager | None = None,
        hydrator: ContextHydrator | None = None,
        verifier: VerificationRunner | None = None,
        bus: EventBus | None = None,
    ):
        self.settings = settings
        self.registry = registry
        self.sessions = sessions or ClaudeSessionManager(settings, registry)
        self.hydrator = hydrator or ContextHydrator(settings)
        self.verifier = verifier or VerificationRunner(
            timeout_s=settings.verify_timeout_s, kill_grace_s=settings.kill_grace_s
        )
        self.bus = bus or EventBus(registry)
        self._running: dict[str, asyncio.Task[FinalSummary]] = {}
        self._sem = asyncio.Semaphore(settings.max_concurrent_tasks)

    # ------------------------------------------------------------------ public API
    async def submit(self, task: TaskInput, task_id: str | None = None, start: bool = True) -> SessionState:
        task_id = str(uuid.UUID(task_id)) if task_id else str(uuid.uuid4())
        if task.workspace_path:
            workspace = Path(task.workspace_path).expanduser().resolve()
        else:
            workspace = (self.settings.workspace_root / task_id).resolve()
        if await self.registry.exists(task_id):
            raise DuplicateTaskError(f"task {task_id} already registered")
        workspace.mkdir(parents=True, exist_ok=True)
        state = await self.registry.create_task(
            SessionState(task_id=task_id, workspace_path=str(workspace), task_input=task)
        )
        await self.bus.publish(task_id, "submitted", "task accepted", TaskStatus.PENDING, workspace=str(workspace))
        if start:
            self.start(task_id)
        return state

    def start(self, task_id: str) -> asyncio.Task[FinalSummary]:
        """Start (or return the already running) background execution for a task."""
        existing = self._running.get(task_id)
        if existing is not None and not existing.done():
            return existing
        t = asyncio.create_task(self.run(task_id), name=f"task-{task_id}")
        self._running[task_id] = t
        t.add_done_callback(lambda _t, tid=task_id: self._running.pop(tid, None) if self._running.get(tid) is _t else None)
        return t

    def is_running(self, task_id: str) -> bool:
        t = self._running.get(task_id)
        return t is not None and not t.done()

    async def wait(self, task_id: str, timeout: float | None = None) -> FinalSummary | None:
        t = self._running.get(task_id)
        if t is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await asyncio.wait_for(asyncio.shield(t), timeout)
        return await self.registry.get_summary(task_id)

    async def cancel(self, task_id: str) -> bool:
        t = self._running.get(task_id)
        if t is None or t.done():
            return False
        t.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await t
        return True

    async def resume_interrupted(self) -> list[str]:
        """Re-enter every non-terminal task (e.g. after a crash) on its existing session."""
        ids = []
        for st in await self.registry.list_resumable():
            if not self.is_running(st.task_id):
                self.start(st.task_id)
                ids.append(st.task_id)
        return ids

    async def shutdown(self) -> None:
        tasks = [t for t in self._running.values() if not t.done()]
        for t in tasks:
            t.cancel()
        for t in tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await t

    # ------------------------------------------------------------------ state machine
    async def _set_status(self, task_id: str, status: TaskStatus, message: str = "", **data: Any) -> None:
        await self.registry.update_status(task_id, status)
        await self.bus.publish(task_id, "status", message or status.value, status, **data)

    async def _turn(self, task_id: str, prompt: str, phase: TaskStatus) -> TurnOutcome:
        def on_line(stream: str, line: str) -> None:
            self.bus.publish_ephemeral(task_id, "output", line, stream=stream, phase=phase.value)

        outcome = await self.sessions.send(task_id, prompt, phase, on_line=on_line)
        await self.bus.publish(
            task_id, "turn", f"turn {outcome.turn.turn_index} ({phase.value}) finished", phase,
            turn_index=outcome.turn.turn_index, session_id=outcome.result.session_id, resumed=outcome.turn.resumed,
            is_error=outcome.result.is_error, attempts=outcome.turn.attempts,
            tokens=outcome.result.usage.total, cost_usd=outcome.result.total_cost_usd,
            response_preview=(outcome.result.result or "")[:500],
        )
        return outcome

    async def _verify(self, task_id: str, state: SessionState) -> VerificationReport:
        await self._set_status(task_id, TaskStatus.VERIFYING)
        task = state.task_input
        report = await self.verifier.verify(state.workspace_path, task.verification_commands, task.extra_env)
        await self.bus.publish(
            task_id, "verification", "verification passed" if report.passed else "verification failed",
            TaskStatus.VERIFYING, passed=report.passed, reason=report.reason,
            results=[{"command": r.command, "exit_code": r.exit_code, "timed_out": r.timed_out,
                      "duration_s": round(r.duration_s, 3)} for r in report.results],
        )
        return report

    async def _prepare_workspace(self, state: SessionState) -> None:
        task = state.task_input
        ws = Path(state.workspace_path)
        ws.mkdir(parents=True, exist_ok=True)
        if task.repo_url and not any(ws.iterdir()):
            await self.bus.publish(state.task_id, "workspace", f"cloning {task.repo_url}")
            res = await run_process(
                ["git", "clone", "--", task.repo_url, "."], cwd=ws, timeout_s=self.settings.verify_timeout_s,
                kill_grace_s=self.settings.kill_grace_s,
            )
            if res.exit_code != 0:
                raise OrchestratorError(f"git clone failed ({res.exit_code}): {res.stderr.strip()[-1000:]}")

    async def run(self, task_id: str) -> FinalSummary:
        async with self._sem:
            return await self._run(task_id)

    async def _run(self, task_id: str) -> FinalSummary:
        state = await self.registry.get(task_id)
        if state.status.is_terminal:
            summary = await self.registry.get_summary(task_id)
            if summary is not None:
                return summary
        task = state.task_input
        max_turns = task.max_turns or self.settings.max_turns
        report: VerificationReport | None = None
        last_message: str | None = None
        failure: str | None = None
        final_status = TaskStatus.FAILED
        try:
            await self._prepare_workspace(state)
            fresh = state.session_id is None
            if fresh:
                # No session exists yet, so (re)starting from hydration cannot create a duplicate session.
                await self._set_status(task_id, TaskStatus.HYDRATING)
                ctx = await self.hydrator.hydrate(
                    task.description, task.context_sources, task.auto_detect_sources, state.workspace_path
                )
                await self.bus.publish(
                    task_id, "context", f"hydrated {sum(a.ok for a in ctx.artifacts)}/{len(ctx.artifacts)} sources",
                    TaskStatus.HYDRATING, truncated=ctx.truncated,
                    sources=[{"kind": a.kind.value, "ref": a.ref, "ok": a.ok, "error": a.error} for a in ctx.artifacts],
                )
                await self._set_status(task_id, TaskStatus.PLANNING)
                out = await self._turn(
                    task_id, plan_prompt(ctx.payload, task.verification_commands, state.workspace_path),
                    TaskStatus.PLANNING,
                )
                last_message = out.result.result
                state = out.state
            else:
                await self.bus.publish(task_id, "resumed", f"resuming session {state.session_id}", state.status,
                                       session_id=state.session_id, turn_count=state.turn_count)

            if state.turn_count <= 1 and state.turn_count < max_turns:
                await self._set_status(task_id, TaskStatus.IMPLEMENTING)
                out = await self._turn(task_id, implement_prompt(task.verification_commands), TaskStatus.IMPLEMENTING)
                last_message = out.result.result
                state = out.state

            heal_attempt = 0
            while True:
                report = await self._verify(task_id, state)
                if report.passed:
                    final_status = TaskStatus.COMPLETED
                    break
                if state.turn_count >= max_turns:
                    failure = f"max_turns_exhausted: verification still failing after {state.turn_count} turns"
                    break
                heal_attempt += 1
                await self._set_status(task_id, TaskStatus.HEALING, f"self-healing attempt {heal_attempt}")
                out = await self._turn(
                    task_id,
                    heal_prompt(report, heal_attempt, max_turns - state.turn_count - 1, self.settings.max_feedback_chars),
                    TaskStatus.HEALING,
                )
                last_message = out.result.result
                state = out.state
        except asyncio.CancelledError:
            final_status, failure = TaskStatus.CANCELLED, "cancelled"
            await self._finish(task_id, final_status, report, last_message, failure, max_turns)
            raise
        except SessionInvariantError as exc:
            failure = f"session_invariant_violation: {exc}"
        except ClaudeError as exc:
            failure = f"{type(exc).__name__}: {exc}"
        except Exception as exc:  # noqa: BLE001 - every failure must end in a terminal state
            log.exception("task %s crashed", task_id)
            failure = f"{type(exc).__name__}: {exc}"
        if last_message is None:
            turns = await self.registry.turns(task_id)
            last_message = turns[-1].response if turns else None
        return await self._finish(task_id, final_status, report, last_message, failure, max_turns)

    async def _finish(self, task_id: str, status: TaskStatus, report: VerificationReport | None,
                      last_message: str | None, failure: str | None, max_turns: int) -> FinalSummary:
        async def write() -> FinalSummary:
            await self.registry.update_status(task_id, status, last_error=failure)
            state = await self.registry.get(task_id)
            summary = FinalSummary(
                task_id=task_id, session_id=state.session_id, status=status, turns_used=state.turn_count,
                max_turns=max_turns, token_usage=state.token_usage, total_cost_usd=state.total_cost_usd,
                verification=report, final_message=last_message, failure_reason=failure,
                workspace_path=state.workspace_path,
            )
            await self.registry.set_summary(summary)
            await self.bus.publish(task_id, status.value.lower(), failure or "all verification checks passed", status,
                                   summary=summary.model_dump(mode="json"))
            return summary
        # Shield so a cancellation arriving mid-write still leaves a terminal record.
        return await asyncio.shield(write())
