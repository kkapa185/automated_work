"""Pydantic v2 models shared across the orchestrator."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TaskStatus(str, Enum):
    PENDING = "PENDING"
    HYDRATING = "HYDRATING"
    PLANNING = "PLANNING"
    IMPLEMENTING = "IMPLEMENTING"
    VERIFYING = "VERIFYING"
    HEALING = "HEALING"
    REVIEWING = "REVIEWING"
    PAUSED_USAGE_LIMIT = "PAUSED_USAGE_LIMIT"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"

    @property
    def is_terminal(self) -> bool:
        return self in TERMINAL_STATUSES


TERMINAL_STATUSES = frozenset({TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED})


class SafetyLevel(str, Enum):
    READ_ONLY = "read_only"
    STANDARD = "standard"
    CUSTOM = "custom"


class SourceKind(str, Enum):
    JIRA = "jira"
    CONFLUENCE = "confluence"
    FILE = "file"
    GIT_DIFF = "git_diff"
    URL = "url"
    STACK_TRACE = "stack_trace"
    TEXT = "text"


# --------------------------------------------------------------------------- task input


class ContextSource(BaseModel):
    """A reference to something that should be ingested into the prompt context."""

    model_config = ConfigDict(frozen=True)

    kind: SourceKind
    ref: str = Field(min_length=1, description="Ticket key, page id, path, URL, git range or raw text")

    def key(self) -> tuple[str, str]:
        return (self.kind.value, self.ref)


class TaskInput(BaseModel):
    description: str = Field(min_length=1, max_length=200_000)
    workspace_path: str | None = Field(
        default=None, description="Existing directory to work in. Defaults to <workspace_root>/<task_id>."
    )
    repo_url: str | None = Field(default=None, description="Git URL cloned into the workspace if it is empty.")
    context_sources: list[ContextSource] = Field(default_factory=list)
    auto_detect_sources: bool = True
    verification_commands: list[str] | None = Field(
        default=None, description="Shell-free commands that must all exit 0. Auto-detected when omitted."
    )
    max_turns: int | None = Field(default=None, ge=2, le=50)
    safety: SafetyLevel = SafetyLevel.STANDARD
    allowed_tools: list[str] | None = Field(default=None, description="Only honoured with safety=custom.")
    extra_env: dict[str, str] = Field(default_factory=dict)
    constraints: list[str] = Field(
        default_factory=list, description="Extra non-negotiable rules injected into every phase prompt."
    )

    @field_validator("verification_commands")
    @classmethod
    def _non_empty_cmds(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        cleaned = [c.strip() for c in v if c and c.strip()]
        return cleaned or None

    @field_validator("allowed_tools")
    @classmethod
    def _clean_tools(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        return [t.strip() for t in v if t.strip()]


# --------------------------------------------------------------------------- context


class ContextArtifact(BaseModel):
    kind: SourceKind
    ref: str
    title: str = ""
    content: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


class CompiledContext(BaseModel):
    payload: str
    artifacts: list[ContextArtifact]
    truncated: bool = False


# --------------------------------------------------------------------------- claude CLI


class TokenUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0

    model_config = ConfigDict(extra="ignore")

    @property
    def total(self) -> int:
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_creation_input_tokens
            + self.cache_read_input_tokens
        )

    def add(self, other: "TokenUsage") -> "TokenUsage":
        return TokenUsage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cache_creation_input_tokens=self.cache_creation_input_tokens + other.cache_creation_input_tokens,
            cache_read_input_tokens=self.cache_read_input_tokens + other.cache_read_input_tokens,
        )


class ClaudeCLIResult(BaseModel):
    """The JSON object printed by ``claude -p ... --output-format json``."""

    model_config = ConfigDict(extra="allow")

    type: str = "result"
    subtype: str | None = None
    is_error: bool = False
    result: str | None = None
    session_id: str
    num_turns: int | None = None
    duration_ms: int | None = None
    duration_api_ms: int | None = None
    total_cost_usd: float | None = None
    usage: TokenUsage = Field(default_factory=TokenUsage)

    @field_validator("usage", mode="before")
    @classmethod
    def _usage_none(cls, v: Any) -> Any:
        return v if v is not None else {}


# --------------------------------------------------------------------------- state


class SessionState(BaseModel):
    task_id: str
    session_id: str | None = None
    planned_session_id: str | None = None
    workspace_path: str
    status: TaskStatus = TaskStatus.PENDING
    turn_count: int = 0
    token_usage: TokenUsage = Field(default_factory=TokenUsage)
    total_cost_usd: float = 0.0
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    last_error: str | None = None

    @property
    def session_cost_usd(self) -> float:
        """Cumulative cost of the claude session so far (turn costs are stored as deltas)."""
        return self.total_cost_usd
    resume_at: datetime | None = None
    paused_phase: TaskStatus | None = None
    task_input: TaskInput


class TurnRecord(BaseModel):
    task_id: str
    turn_index: int
    phase: TaskStatus
    session_id: str
    resumed: bool
    prompt: str
    response: str | None
    is_error: bool = False
    usage: TokenUsage = Field(default_factory=TokenUsage)
    cost_usd: float | None = None
    duration_s: float = 0.0
    attempts: int = 1
    permission_denials: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)


# --------------------------------------------------------------------------- verification


class CommandResult(BaseModel):
    command: str
    kind: str = "check"
    exit_code: int | None
    stdout: str = ""
    stderr: str = ""
    duration_s: float = 0.0
    timed_out: bool = False
    error: str | None = None

    @property
    def passed(self) -> bool:
        return self.exit_code == 0 and not self.timed_out and self.error is None


class VerificationReport(BaseModel):
    passed: bool
    results: list[CommandResult] = Field(default_factory=list)
    reason: str | None = None
    created_at: datetime = Field(default_factory=utcnow)

    @classmethod
    def from_results(cls, results: list[CommandResult], reason: str | None = None) -> "VerificationReport":
        passed = bool(results) and all(r.passed for r in results)
        if not results and reason is None:
            reason = "no verification commands were found or configured"
        return cls(passed=passed, results=results, reason=reason)

    def failure_digest(self, max_chars: int = 12_000) -> str:
        """Human/LLM readable description of every failing check, bounded in size."""
        if self.passed:
            return "All verification checks passed."
        parts: list[str] = []
        if self.reason:
            parts.append(f"Verification problem: {self.reason}")
        failing = [r for r in self.results if not r.passed]
        per = max(500, max_chars // max(1, len(failing))) if failing else max_chars
        for r in failing:
            status = "TIMED OUT" if r.timed_out else f"exit code {r.exit_code}"
            block = [f"### `{r.command}` -> {status}"]
            if r.error:
                block.append(f"error: {r.error}")
            if r.stdout.strip():
                block.append("stdout:\n```\n" + _tail(r.stdout, per // 2) + "\n```")
            if r.stderr.strip():
                block.append("stderr:\n```\n" + _tail(r.stderr, per // 2) + "\n```")
            parts.append("\n".join(block))
        return _tail("\n\n".join(parts), max_chars)


def _tail(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return "...[truncated]...\n" + text[-limit:]


# --------------------------------------------------------------------------- events / summary


class TaskEvent(BaseModel):
    task_id: str
    seq: int = 0
    type: str
    status: TaskStatus | None = None
    message: str = ""
    data: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)


class FinalSummary(BaseModel):
    task_id: str
    session_id: str | None
    status: TaskStatus
    turns_used: int
    max_turns: int
    token_usage: TokenUsage
    total_cost_usd: float
    verification: VerificationReport | None
    final_message: str | None
    failure_reason: str | None = None
    review_verdict: str | None = None
    workspace_path: str
    finished_at: datetime = Field(default_factory=utcnow)


class TaskCreated(BaseModel):
    task_id: str
    status: TaskStatus
    workspace_path: str
