"""ClaudeSessionManager: drives exactly one ``claude`` CLI session per task."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Awaitable, Callable

from pydantic import ValidationError

from config import Settings
from connectors.base import backoff_delay
from process import LineCallback, ProcessResult, run_process
from registry import SessionInvariantError, SessionRegistry
from schemas import ClaudeCLIResult, SafetyLevel, SessionState, TaskInput, TaskStatus, TurnRecord
from usage_limits import UsageLimitInfo, parse_usage_limit

log = logging.getLogger(__name__)

ALL_TOOLS = ("Bash", "Edit", "Write", "Read", "Glob", "Grep", "WebFetch", "WebSearch", "NotebookEdit", "TodoWrite")

TRANSIENT_RE = re.compile(
    r"overloaded|rate[ _-]?limit|too many requests|\b(?:429|500|502|503|504|529)\b|ECONNRESET|ETIMEDOUT|"
    r"ECONNREFUSED|EAI_AGAIN|socket hang up|network error|connection (?:error|reset|refused)|"
    r"temporarily unavailable|service unavailable|request timed out",
    re.IGNORECASE,
)
FATAL_RE = re.compile(r"invalid api key|not logged in|authentication|unauthorized|permission denied|\b401\b|\b403\b", re.IGNORECASE)

Sleeper = Callable[[float], Awaitable[None]]


class ClaudeError(Exception):
    def __init__(self, message: str, *, result: ProcessResult | None = None):
        super().__init__(message)
        self.result = result


class ClaudeTransientError(ClaudeError):
    """Retryable: timeouts, API overload/rate limits, network failures, unparsable output."""


class ClaudeFatalError(ClaudeError):
    """Non-retryable: missing binary, auth failures, unknown non-zero exits."""


class ClaudeUsageLimitError(ClaudeError):
    """The account's 5-hour or weekly allowance is exhausted; retry the same turn after ``info.resets_at``."""

    def __init__(self, message: str, info: UsageLimitInfo, *, result: ProcessResult | None = None):
        super().__init__(message, result=result)
        self.info = info


def detect_usage_limit(proc: ProcessResult, parsed: ClaudeCLIResult | None) -> UsageLimitInfo | None:
    """Only failed invocations are inspected, so an answer that merely *discusses* limits never matches."""
    failed = proc.exit_code != 0 or parsed is None or parsed.is_error
    if not failed:
        return None
    blob = "\n".join(x for x in (parsed.result if parsed else None, proc.stderr, proc.stdout if parsed is None else None) if x)
    return parse_usage_limit(blob)


@dataclass
class TurnOutcome:
    result: ClaudeCLIResult
    turn: TurnRecord
    state: SessionState


def parse_cli_json(stdout: str) -> ClaudeCLIResult | None:
    """Return the last ``{"type": "result", ...}``-like JSON object in stdout, tolerating preamble lines."""
    text = stdout.strip()
    if not text:
        return None
    candidates: list[str] = [text]
    candidates.extend(reversed([ln.strip() for ln in text.splitlines() if ln.strip().startswith("{")]))
    for cand in candidates:
        try:
            obj = json.loads(cand)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, list):  # stream-json style array: pick last result object
            obj = next((o for o in reversed(obj) if isinstance(o, dict) and o.get("type") == "result"), None)
        if isinstance(obj, dict) and obj.get("session_id"):
            try:
                return ClaudeCLIResult.model_validate(obj)
            except ValidationError:
                continue
    # Last resort: the final balanced {...} block.
    start = text.rfind("\n{")
    if start != -1:
        try:
            obj = json.loads(text[start + 1:])
            if isinstance(obj, dict) and obj.get("session_id"):
                return ClaudeCLIResult.model_validate(obj)
        except (json.JSONDecodeError, ValidationError):
            pass
    return None


def classify_failure(proc: ProcessResult, parsed: ClaudeCLIResult | None) -> type[ClaudeError] | None:
    """Return the error class for a failed invocation, or None if it succeeded."""
    if proc.timed_out:
        return ClaudeTransientError
    blob = f"{proc.stderr}\n{parsed.result if parsed and parsed.result else ''}"
    if parsed is not None and not parsed.is_error and proc.exit_code == 0:
        return None
    if parsed is not None and parsed.is_error:
        if TRANSIENT_RE.search(blob):
            return ClaudeTransientError
        # e.g. error_max_turns / error_during_execution: the session progressed; let the orchestrator verify.
        return None
    if FATAL_RE.search(blob):
        return ClaudeFatalError
    if TRANSIENT_RE.search(blob):
        return ClaudeTransientError
    if parsed is None and proc.exit_code == 0:
        return ClaudeTransientError  # truncated / garbled output
    if parsed is not None:
        return None  # non-zero exit but a valid result payload
    return ClaudeFatalError


class ClaudeSessionManager:
    """Enforces the 1 task -> 1 ``claude`` session invariant.

    * the first turn uses ``claude -p <prompt> --output-format json`` and binds the
      returned ``session_id`` in the registry;
    * every later turn (and every retry once a session is bound) uses
      ``claude --resume <session_id> -p <prompt> --output-format json``;
    * a response carrying a different ``session_id`` aborts with SessionInvariantError.
    """

    def __init__(self, settings: Settings, registry: SessionRegistry, sleep: Sleeper | None = None):
        self.settings = settings
        self.registry = registry
        self._sleep = sleep or asyncio.sleep
        self._locks: dict[str, asyncio.Lock] = {}

    def _lock(self, task_id: str) -> asyncio.Lock:
        lock = self._locks.get(task_id)
        if lock is None:
            lock = self._locks[task_id] = asyncio.Lock()
        return lock

    # ------------------------------------------------------------------ argv
    def tools_for(self, task: TaskInput) -> list[str]:
        if task.safety == SafetyLevel.READ_ONLY:
            return list(self.settings.allowed_tools_safe)
        if task.safety == SafetyLevel.CUSTOM and task.allowed_tools:
            return list(task.allowed_tools)
        return list(self.settings.allowed_tools_standard)

    def build_argv(self, prompt: str | None, session_id: str | None, task: TaskInput) -> list[str]:
        s = self.settings
        argv = [s.claude_binary]
        if session_id:
            argv += ["--resume", session_id]
        argv.append("-p")
        if prompt is not None:
            argv.append(prompt)
        argv += ["--output-format", "json"]
        tools = self.tools_for(task)
        if tools:
            argv += ["--allowedTools", ",".join(tools)]
        if task.safety == SafetyLevel.READ_ONLY:
            denied = [t for t in ALL_TOOLS if t not in tools]
            if denied:
                argv += ["--disallowedTools", ",".join(denied)]
        mode = s.permission_mode if task.safety != SafetyLevel.READ_ONLY else "default"
        if mode:
            argv += ["--permission-mode", mode]
        if s.model:
            argv += ["--model", s.model]
        argv += list(s.claude_extra_args)
        return argv

    def _env(self, task: TaskInput) -> dict[str, str]:
        env = {k: v for k, v in os.environ.items() if k not in set(self.settings.cli_env_unset)}
        env.update(task.extra_env)
        return env

    # ------------------------------------------------------------------ turns
    async def send(
        self, task_id: str, prompt: str, phase: TaskStatus, on_line: LineCallback | None = None
    ) -> TurnOutcome:
        """Send one turn to the task's session (starting it if this is the very first turn)."""
        async with self._lock(task_id):
            state = await self.registry.get(task_id)
            task = state.task_input
            bound = state.session_id
            resumed = bound is not None
            use_stdin = len(prompt.encode()) > self.settings.max_argv_prompt_bytes
            attempt = 0
            t0 = time.monotonic()
            while True:
                argv = self.build_argv(None if use_stdin else prompt, bound, task)
                log.info("task %s: claude %s (attempt %d)", task_id, "resume" if bound else "start", attempt + 1)
                try:
                    proc = await run_process(
                        argv,
                        cwd=state.workspace_path,
                        env=self._env(task),
                        timeout_s=self.settings.cli_timeout_s,
                        stdin_data=prompt.encode() if use_stdin else None,
                        on_line=on_line,
                        kill_grace_s=self.settings.kill_grace_s,
                    )
                except FileNotFoundError as exc:
                    raise ClaudeFatalError(f"claude binary not found: {self.settings.claude_binary}") from exc
                except PermissionError as exc:
                    raise ClaudeFatalError(f"claude binary not executable: {exc}") from exc

                parsed = parse_cli_json(proc.stdout)
                if parsed is not None:
                    if bound is None:
                        # Bind immediately so any retry resumes this session instead of starting another.
                        await self.registry.bind_session(task_id, parsed.session_id)
                        bound = parsed.session_id
                    elif parsed.session_id != bound:
                        raise SessionInvariantError(
                            f"claude returned session {parsed.session_id} while resuming {bound} for task {task_id}"
                        )

                limit = detect_usage_limit(proc, parsed)
                if limit is not None:
                    raise ClaudeUsageLimitError(f"usage limit reached: {limit.message}", limit, result=proc)

                err_cls = classify_failure(proc, parsed)
                if err_cls is None:
                    assert parsed is not None
                    break
                detail = (proc.stderr.strip() or (parsed.result if parsed else "") or proc.stdout.strip())[-2000:]
                msg = f"claude {'timed out' if proc.timed_out else f'exited {proc.exit_code}'}: {detail}"
                if err_cls is ClaudeFatalError or attempt >= self.settings.max_transient_retries:
                    raise err_cls(msg, result=proc)
                delay = backoff_delay(attempt, self.settings.backoff_base_s, self.settings.backoff_max_s)
                log.warning("task %s: transient claude failure (%s); retrying in %.1fs", task_id, msg[:200], delay)
                attempt += 1
                await self._sleep(delay)

            turn = TurnRecord(
                task_id=task_id,
                turn_index=state.turn_count + 1,
                phase=phase,
                session_id=parsed.session_id,
                resumed=resumed,
                prompt=prompt,
                response=parsed.result,
                is_error=parsed.is_error,
                usage=parsed.usage,
                cost_usd=parsed.total_cost_usd,
                duration_s=time.monotonic() - t0,
                attempts=attempt + 1,
                permission_denials=[d for d in (parsed.model_extra or {}).get("permission_denials") or [] if isinstance(d, dict)],
            )
            new_state = await self.registry.record_turn(turn)
            return TurnOutcome(result=parsed, turn=turn, state=new_state)
