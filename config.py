"""Runtime configuration for the Task Orchestrator.

All settings are read from environment variables prefixed with ``ORCH_``
(e.g. ``ORCH_MAX_TURNS=7``). Jira/Confluence credentials additionally accept
their conventional un-prefixed names (``JIRA_BASE_URL``, ``JIRA_API_TOKEN`` ...).
List-valued settings are comma separated.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

from pydantic import BaseModel, Field, field_validator

ENV_PREFIX = "ORCH_"

DEFAULT_SAFE_TOOLS = ["Read", "Glob", "Grep"]
DEFAULT_STANDARD_TOOLS = ["Bash", "Edit", "Write", "Read", "Glob", "Grep"]


class Settings(BaseModel):
    """Validated application settings."""

    # --- claude CLI ---------------------------------------------------------
    claude_binary: str = "claude"
    claude_extra_args: list[str] = Field(default_factory=list)
    permission_mode: str | None = "acceptEdits"
    model: str | None = None
    allowed_tools_safe: list[str] = Field(default_factory=lambda: list(DEFAULT_SAFE_TOOLS))
    allowed_tools_standard: list[str] = Field(default_factory=lambda: list(DEFAULT_STANDARD_TOOLS))

    # --- storage / workspaces ------------------------------------------------
    workspace_root: Path = Path("/tmp/workspaces")
    db_path: Path = Path("./orchestrator.db")

    # --- timeouts & budgets --------------------------------------------------
    cli_timeout_s: float = 3600.0
    verify_timeout_s: float = 900.0
    kill_grace_s: float = 5.0
    max_turns: int = 8
    max_reviews: int = 2  # requirement-review turns after verification first passes
    # Milestone mode (large builds): extra turn budget per milestone, heal turns per milestone, global cap.
    turns_per_milestone: int = 3
    milestone_heal_turns: int = 2
    max_turns_cap: int = 60
    max_transient_retries: int = 3
    backoff_base_s: float = 2.0
    backoff_max_s: float = 60.0
    max_concurrent_tasks: int = 4

    # --- subscription usage limits (5-hour / weekly) -------------------------
    usage_limit_margin_s: float = 120.0
    usage_probe_schedule_s: list[float] = Field(default_factory=lambda: [600.0, 1200.0, 2400.0, 3600.0])
    usage_gate_poll_s: float = 60.0
    # Environment variables removed before spawning the nested claude CLI (e.g. the parent session's identity).
    cli_env_unset: list[str] = Field(default_factory=list)
    # Do not let the nested CLI load the account's MCP connectors (Slack, Jira, ...): tasks get context
    # through the orchestrator's own connectors, and unreachable MCP hosts only slow every turn down.
    cli_isolate_mcp: bool = True
    # Choose the session id ourselves (`--session-id`) and persist it before the first call, so that a
    # first turn that times out or crashes before printing JSON is retried on the SAME session.
    preassign_session_id: bool = True
    # While a (possibly hour-long) turn runs, publish workspace activity so observers see progress.
    heartbeat_interval_s: float = 60.0
    max_argv_prompt_bytes: int = 100_000  # larger prompts are piped via stdin (Linux MAX_ARG_STRLEN is 128KiB)

    # --- context sizing ------------------------------------------------------
    max_context_chars: int = 120_000
    max_artifact_chars: int = 40_000
    max_feedback_chars: int = 12_000
    http_timeout_s: float = 30.0
    http_max_retries: int = 3

    # --- Jira ----------------------------------------------------------------
    jira_base_url: str | None = None
    jira_email: str | None = None
    jira_api_token: str | None = None
    jira_api_version: str = "2"
    jira_acceptance_criteria_field: str | None = None
    jira_max_comments: int = 20

    # --- Confluence ----------------------------------------------------------
    confluence_base_url: str | None = None
    confluence_email: str | None = None
    confluence_api_token: str | None = None

    @field_validator("max_turns")
    @classmethod
    def _min_turns(cls, v: int) -> int:
        if v < 2:
            raise ValueError("max_turns must be >= 2 (plan + implement)")
        return v

    @field_validator("jira_base_url", "confluence_base_url")
    @classmethod
    def _strip_slash(cls, v: str | None) -> str | None:
        return v.rstrip("/") if v else v

    @property
    def jira_configured(self) -> bool:
        return bool(self.jira_base_url and self.jira_api_token)

    @property
    def confluence_configured(self) -> bool:
        return bool(self.confluence_base_url and self.confluence_api_token)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None, **overrides: Any) -> "Settings":
        env = os.environ if env is None else env
        data: dict[str, Any] = {}
        list_fields = {
            name for name, f in cls.model_fields.items() if "list" in str(f.annotation)
        }
        aliases = {
            "jira_base_url": "JIRA_BASE_URL",
            "jira_email": "JIRA_EMAIL",
            "jira_api_token": "JIRA_API_TOKEN",
            "confluence_base_url": "CONFLUENCE_BASE_URL",
            "confluence_email": "CONFLUENCE_EMAIL",
            "confluence_api_token": "CONFLUENCE_API_TOKEN",
        }
        for name in cls.model_fields:
            raw = env.get(ENV_PREFIX + name.upper())
            if raw is None and name in aliases:
                raw = env.get(aliases[name])
            if raw is None:
                continue
            if name in list_fields:
                data[name] = [p.strip() for p in raw.split(",") if p.strip()]
                if "float" in str(cls.model_fields[name].annotation):
                    data[name] = [float(x) for x in data[name]]
            elif name in {"permission_mode", "model"} and raw.strip().lower() in {"", "none"}:
                data[name] = None
            else:
                data[name] = raw
        data.update(overrides)
        return cls(**data)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings.from_env()
