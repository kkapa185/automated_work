"""Task orchestrator: Hydrate -> Plan -> Implement -> Verify -> (Heal -> Verify)* on ONE claude session."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any

from claude_session import ClaudeError, ClaudeSessionManager, ClaudeUsageLimitError, TurnOutcome
from config import Settings
from connectors import ContextHydrator
from process import run_process
from prompts import (
    heal_prompt, implement_prompt, parse_review_verdict, permission_denials_note, plan_prompt, review_prompt,
)
from registry import DuplicateTaskError, SessionInvariantError, SessionRegistry
from schemas import (
    FinalSummary, SessionState, TaskEvent, TaskInput, TaskStatus, VerificationReport,
)
from usage_limits import Clock, UsageGate, compute_resume_at, parse_usage_limit, utc_now
from verification import VerificationRunner

log = logging.getLogger(__name__)

HEARTBEAT_SKIP_DIRS = frozenset({".git", "node_modules", ".venv", "venv", "__pycache__", "target", ".pytest_cache", "dist", "build"})


def workspace_activity(root: str, max_files: int = 50_000) -> dict[str, Any]:
    """Cheap snapshot of a workspace: file count, total bytes and the most recently modified file."""
    files = size = 0
    newest, newest_path = 0.0, ""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in HEARTBEAT_SKIP_DIRS]
        for fn in filenames:
            fp = os.path.join(dirpath, fn)
            try:
                st = os.stat(fp)
            except OSError:
                continue
            files += 1
            size += st.st_size
            if st.st_mtime > newest:
                newest, newest_path = st.st_mtime, os.path.relpath(fp, root)
            if files >= max_files:
                return {"files": files, "bytes": size, "last_modified": newest_path, "last_modified_at": newest}
    return {"files": files, "bytes": size, "last_modified": newest_path, "last_modified_at": newest}

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
        gate: UsageGate | None = None,
        clock: Clock = utc_now,
    ):
        self.settings = settings
        self.registry = registry
        self.sessions = sessions or ClaudeSessionManager(settings, registry)
        self.hydrator = hydrator or ContextHydrator(settings)
        self.verifier = verifier or VerificationRunner(
            timeout_s=settings.verify_timeout_s, kill_grace_s=settings.kill_grace_s
        )
        self.bus = bus or EventBus(registry)
        self.clock = clock
        self.gate = gate or UsageGate(clock=clock, poll_s=settings.usage_gate_poll_s)
        self._running: dict[str, asyncio.Task[FinalSummary]] = {}
        self._pending_denials: dict[str, list[dict[str, Any]]] = {}
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
        """Re-enter every non-terminal task (e.g. after a crash) on its existing session.

        Tasks that were paused on a usage limit re-arm the shared gate with their persisted
        ``resume_at``, so the restarted process sleeps until the reset instead of hammering the API.
        """
        ids = []
        for st in await self.registry.list_resumable():
            if st.status == TaskStatus.PAUSED_USAGE_LIMIT and st.resume_at is not None:
                self.gate.block(st.resume_at)
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

    # ------------------------------------------------------------------ helpers
    async def _set_status(self, task_id: str, status: TaskStatus, message: str = "", **data: Any) -> None:
        await self.registry.update_status(task_id, status)
        await self.bus.publish(task_id, "status", message or status.value, status, **data)

    async def _wait_for_gate(self, task_id: str, phase: TaskStatus, reason: str) -> None:
        """Park the task until the shared usage gate opens, persisting the pause for restarts."""
        until = self.gate.blocked_until
        if until is None:
            return
        await self.registry.set_pause(task_id, until, phase, reason)
        await self.bus.publish(
            task_id, "paused", f"usage limit: waiting until {until.isoformat()}", TaskStatus.PAUSED_USAGE_LIMIT,
            resume_at=until.isoformat(), phase=phase.value, reason=reason,
            limit_kind=self.gate.info.kind if self.gate.info else None,
        )
        waited = await self.gate.wait()
        await self.registry.clear_pause(task_id, phase)
        await self.bus.publish(task_id, "resumed", f"usage limit reset; continuing {phase.value}", phase,
                               waited_s=round(waited, 1))

    async def _turn(self, task_id: str, prompt: str, phase: TaskStatus) -> TurnOutcome:
        """One logical turn. Usage-limit pauses re-send the same prompt to the same session afterwards
        and consume neither the turn budget nor transient retries."""
        def on_line(stream: str, line: str) -> None:
            self.bus.publish_ephemeral(task_id, "output", line, stream=stream, phase=phase.value)

        prompt = prompt + permission_denials_note(self._pending_denials.pop(task_id, []))
        consecutive_limits = 0
        hb = asyncio.create_task(self._heartbeat(task_id, phase))
        try:
            return await self._turn_inner(task_id, prompt, phase, on_line, consecutive_limits)
        finally:
            hb.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await hb

    async def _heartbeat(self, task_id: str, phase: TaskStatus) -> None:
        interval = self.settings.heartbeat_interval_s
        if interval <= 0:
            return
        state = await self.registry.get(task_id)
        start = time.monotonic()
        while True:
            await asyncio.sleep(interval)
            act = await asyncio.to_thread(workspace_activity, state.workspace_path)
            elapsed = round(time.monotonic() - start)
            self.bus.publish_ephemeral(
                task_id, "heartbeat", f"{phase.value} running for {elapsed}s; workspace has {act['files']} files",
                phase=phase.value, elapsed_s=elapsed, **act,
            )
            log.info("task %s: %s %ss, %d files, last change %s", task_id, phase.value, elapsed, act["files"],
                     act["last_modified"])

    async def _turn_inner(self, task_id: str, prompt: str, phase: TaskStatus, on_line, consecutive_limits: int) -> TurnOutcome:
        while True:
            if self.gate.is_blocked:
                await self._wait_for_gate(task_id, phase, "usage limit reached by another task")
            try:
                outcome = await self.sessions.send(task_id, prompt, phase, on_line=on_line)
            except ClaudeUsageLimitError as exc:
                consecutive_limits += 1
                now = self.clock()
                # Re-parse relative to the orchestrator's clock ("resets 3pm" means the next 3pm after *now*).
                info = parse_usage_limit(exc.info.message, now) or exc.info
                resume_at = compute_resume_at(
                    info, now, consecutive_limits, self.settings.usage_limit_margin_s,
                    self.settings.usage_probe_schedule_s,
                )
                self.gate.block(resume_at, info)
                log.warning("task %s: %s; pausing until %s", task_id, info.message, resume_at.isoformat())
                await self._wait_for_gate(task_id, phase, info.message)
                continue
            break
        if outcome.turn.permission_denials:
            self._pending_denials[task_id] = outcome.turn.permission_denials
        await self.bus.publish(
            task_id, "turn", f"turn {outcome.turn.turn_index} ({phase.value}) finished", phase,
            turn_index=outcome.turn.turn_index, session_id=outcome.result.session_id, resumed=outcome.turn.resumed,
            is_error=outcome.result.is_error, attempts=outcome.turn.attempts,
            tokens=outcome.result.usage.total, cost_usd=outcome.result.total_cost_usd,
            permission_denials=len(outcome.turn.permission_denials),
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
            results=[{"command": r.command, "kind": r.kind, "exit_code": r.exit_code, "timed_out": r.timed_out,
                      "duration_s": round(r.duration_s, 3), "error": r.error} for r in report.results],
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

    # ------------------------------------------------------------------ state machine
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
        cons = task.constraints
        max_turns = task.max_turns or self.settings.max_turns
        max_reviews = self.settings.max_reviews
        report: VerificationReport | None = None
        last_message: str | None = None
        failure: str | None = None
        verdict: str | None = None
        final_status = TaskStatus.FAILED
        try:
            await self._prepare_workspace(state)
            history = await self.registry.turns(task_id)
            phases = [t.phase for t in history]
            if state.session_id is None:
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
                    task_id, plan_prompt(ctx.payload, task.verification_commands, state.workspace_path, cons),
                    TaskStatus.PLANNING,
                )
                last_message = out.result.result
                state = out.state
                phases.append(TaskStatus.PLANNING)
            else:
                await self.bus.publish(task_id, "resumed", f"resuming session {state.session_id}", state.status,
                                       session_id=state.session_id, turn_count=state.turn_count)

            if TaskStatus.IMPLEMENTING not in phases and state.turn_count < max_turns:
                await self._set_status(task_id, TaskStatus.IMPLEMENTING)
                out = await self._turn(task_id, implement_prompt(task.verification_commands, cons),
                                       TaskStatus.IMPLEMENTING)
                last_message = out.result.result
                state = out.state

            reviews = [t for t in history if t.phase == TaskStatus.REVIEWING]
            reviews_done = len(reviews)
            # A review that changed nothing ("PASS") means the next green verification completes the task.
            review_clean = bool(reviews) and parse_review_verdict(reviews[-1].response) == "PASS"
            if reviews:
                verdict = parse_review_verdict(reviews[-1].response)
            heal_attempt = sum(1 for t in history if t.phase == TaskStatus.HEALING)
            while True:
                report = await self._verify(task_id, state)
                if report.passed:
                    if review_clean or reviews_done >= max_reviews:
                        final_status = TaskStatus.COMPLETED
                        break
                    if state.turn_count >= max_turns:
                        final_status = TaskStatus.COMPLETED
                        verdict = verdict or "SKIPPED_BUDGET"
                        break
                    reviews_done += 1
                    await self._set_status(task_id, TaskStatus.REVIEWING, f"requirements review {reviews_done}")
                    out = await self._turn(task_id, review_prompt(reviews_done, max_reviews, cons),
                                           TaskStatus.REVIEWING)
                    last_message = out.result.result
                    state = out.state
                    verdict = parse_review_verdict(out.result.result)
                    review_clean = verdict == "PASS"
                    continue
                review_clean = False
                if state.turn_count >= max_turns:
                    failure = f"max_turns_exhausted: verification still failing after {state.turn_count} turns"
                    break
                heal_attempt += 1
                await self._set_status(task_id, TaskStatus.HEALING, f"self-healing attempt {heal_attempt}")
                out = await self._turn(
                    task_id,
                    heal_prompt(report, heal_attempt, max_turns - state.turn_count - 1,
                                self.settings.max_feedback_chars, cons),
                    TaskStatus.HEALING,
                )
                last_message = out.result.result
                state = out.state
        except asyncio.CancelledError:
            final_status, failure = TaskStatus.CANCELLED, "cancelled"
            await self._finish(task_id, final_status, report, last_message, failure, max_turns, verdict)
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
        return await self._finish(task_id, final_status, report, last_message, failure, max_turns, verdict)

    async def _finish(self, task_id: str, status: TaskStatus, report: VerificationReport | None,
                      last_message: str | None, failure: str | None, max_turns: int,
                      review_verdict: str | None = None) -> FinalSummary:
        async def write() -> FinalSummary:
            await self.registry.update_status(task_id, status, last_error=failure)
            state = await self.registry.get(task_id)
            summary = FinalSummary(
                task_id=task_id, session_id=state.session_id, status=status, turns_used=state.turn_count,
                max_turns=max_turns, token_usage=state.token_usage, total_cost_usd=state.total_cost_usd,
                verification=report, final_message=last_message, failure_reason=failure,
                workspace_path=state.workspace_path, review_verdict=review_verdict,
            )
            await self.registry.set_summary(summary)
            await self.bus.publish(task_id, status.value.lower(), failure or "all verification checks passed", status,
                                   summary=summary.model_dump(mode="json"))
            return summary
        # Shield so a cancellation arriving mid-write still leaves a terminal record.
        return await asyncio.shield(write())
