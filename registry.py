"""SQLite-backed session registry enforcing the task_id -> session_id invariant."""

from __future__ import annotations

import asyncio
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from schemas import (
    TERMINAL_STATUSES, FinalSummary, SessionState, TaskEvent, TaskInput, TaskStatus, TokenUsage, TurnRecord, utcnow,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    task_id        TEXT PRIMARY KEY,
    session_id     TEXT UNIQUE,
    workspace_path TEXT NOT NULL,
    status         TEXT NOT NULL,
    turn_count     INTEGER NOT NULL DEFAULT 0,
    token_usage    TEXT NOT NULL DEFAULT '{}',
    total_cost_usd REAL NOT NULL DEFAULT 0,
    task_input     TEXT NOT NULL,
    last_error     TEXT,
    summary        TEXT,
    resume_at      TEXT,
    paused_phase   TEXT,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS turns (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id     TEXT NOT NULL REFERENCES sessions(task_id),
    turn_index  INTEGER NOT NULL,
    payload     TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    UNIQUE(task_id, turn_index)
);
CREATE TABLE IF NOT EXISTS events (
    task_id     TEXT NOT NULL,
    seq         INTEGER NOT NULL,
    payload     TEXT NOT NULL,
    PRIMARY KEY (task_id, seq)
);
"""


class RegistryError(Exception):
    pass


class DuplicateTaskError(RegistryError):
    pass


class TaskNotFoundError(RegistryError):
    pass


class SessionInvariantError(RegistryError):
    """Raised whenever an operation would map a task to more than one claude session."""


class SessionRegistry:
    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.executescript(SCHEMA)
            cols = {r["name"] for r in self._conn.execute("PRAGMA table_info(sessions)").fetchall()}
            for col in ("resume_at", "paused_phase"):  # forward migration for databases created before v1.1
                if col not in cols:
                    self._conn.execute(f"ALTER TABLE sessions ADD COLUMN {col} TEXT")

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ------------------------------------------------------------------ helpers
    async def _run(self, fn, *args):  # type: ignore[no-untyped-def]
        return await asyncio.to_thread(self._locked, fn, *args)

    def _locked(self, fn, *args):  # type: ignore[no-untyped-def]
        with self._lock:
            return fn(*args)

    @staticmethod
    def _row_to_state(row: sqlite3.Row) -> SessionState:
        return SessionState(
            task_id=row["task_id"],
            session_id=row["session_id"],
            workspace_path=row["workspace_path"],
            status=TaskStatus(row["status"]),
            turn_count=row["turn_count"],
            token_usage=TokenUsage.model_validate_json(row["token_usage"]),
            total_cost_usd=row["total_cost_usd"],
            task_input=TaskInput.model_validate_json(row["task_input"]),
            last_error=row["last_error"],
            resume_at=datetime.fromisoformat(row["resume_at"]) if row["resume_at"] else None,
            paused_phase=TaskStatus(row["paused_phase"]) if row["paused_phase"] else None,
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def _get_row(self, task_id: str) -> sqlite3.Row:
        row = self._conn.execute("SELECT * FROM sessions WHERE task_id=?", (task_id,)).fetchone()
        if row is None:
            raise TaskNotFoundError(task_id)
        return row

    # ------------------------------------------------------------------ tasks
    async def create_task(self, state: SessionState) -> SessionState:
        def op() -> None:
            try:
                self._conn.execute(
                    "INSERT INTO sessions (task_id, session_id, workspace_path, status, turn_count, token_usage,"
                    " total_cost_usd, task_input, last_error, created_at, updated_at)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        state.task_id, state.session_id, state.workspace_path, state.status.value, state.turn_count,
                        state.token_usage.model_dump_json(), state.total_cost_usd, state.task_input.model_dump_json(),
                        state.last_error, state.created_at.isoformat(), state.updated_at.isoformat(),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise DuplicateTaskError(f"task {state.task_id} already registered") from exc

        await self._run(op)
        return state

    async def get(self, task_id: str) -> SessionState:
        return await self._run(lambda: self._row_to_state(self._get_row(task_id)))

    async def exists(self, task_id: str) -> bool:
        def op() -> bool:
            return self._conn.execute("SELECT 1 FROM sessions WHERE task_id=?", (task_id,)).fetchone() is not None
        return await self._run(op)

    async def list(self, limit: int = 100, status: TaskStatus | None = None) -> list[SessionState]:
        def op() -> list[SessionState]:
            if status:
                rows = self._conn.execute(
                    "SELECT * FROM sessions WHERE status=? ORDER BY created_at DESC LIMIT ?", (status.value, limit)
                ).fetchall()
            else:
                rows = self._conn.execute("SELECT * FROM sessions ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
            return [self._row_to_state(r) for r in rows]
        return await self._run(op)

    async def list_resumable(self) -> list[SessionState]:
        terminal = tuple(s.value for s in TERMINAL_STATUSES)
        def op() -> list[SessionState]:
            rows = self._conn.execute(
                f"SELECT * FROM sessions WHERE status NOT IN ({','.join('?' * len(terminal))}) ORDER BY created_at",
                terminal,
            ).fetchall()
            return [self._row_to_state(r) for r in rows]
        return await self._run(op)

    async def bind_session(self, task_id: str, session_id: str) -> None:
        """Bind a claude session to a task exactly once. Rebinding to a different id is forbidden."""
        def op() -> None:
            row = self._get_row(task_id)
            current = row["session_id"]
            if current is not None:
                if current != session_id:
                    raise SessionInvariantError(
                        f"task {task_id} is bound to session {current}; refusing to rebind to {session_id}"
                    )
                return
            try:
                cur = self._conn.execute(
                    "UPDATE sessions SET session_id=?, updated_at=? WHERE task_id=? AND session_id IS NULL",
                    (session_id, utcnow().isoformat(), task_id),
                )
            except sqlite3.IntegrityError as exc:
                raise SessionInvariantError(f"session {session_id} already belongs to another task") from exc
            if cur.rowcount != 1:
                raise SessionInvariantError(f"concurrent bind detected for task {task_id}")
        await self._run(op)

    async def update_status(self, task_id: str, status: TaskStatus, last_error: str | None = None) -> None:
        def op() -> None:
            self._get_row(task_id)
            self._conn.execute(
                "UPDATE sessions SET status=?, last_error=COALESCE(?, last_error), updated_at=? WHERE task_id=?",
                (status.value, last_error, utcnow().isoformat(), task_id),
            )
        await self._run(op)

    async def set_pause(self, task_id: str, resume_at: datetime, phase: TaskStatus, reason: str) -> None:
        """Persist a usage-limit pause so a restarted process knows when to continue."""
        def op() -> None:
            self._get_row(task_id)
            self._conn.execute(
                "UPDATE sessions SET status=?, resume_at=?, paused_phase=?, last_error=?, updated_at=? WHERE task_id=?",
                (TaskStatus.PAUSED_USAGE_LIMIT.value, resume_at.isoformat(), phase.value, reason,
                 utcnow().isoformat(), task_id),
            )
        await self._run(op)

    async def clear_pause(self, task_id: str, status: TaskStatus) -> None:
        def op() -> None:
            self._conn.execute(
                "UPDATE sessions SET status=?, resume_at=NULL, paused_phase=NULL, updated_at=? WHERE task_id=?",
                (status.value, utcnow().isoformat(), task_id),
            )
        await self._run(op)

    # ------------------------------------------------------------------ turns
    async def record_turn(self, turn: TurnRecord) -> SessionState:
        """Persist a turn and atomically bump turn_count / usage / cost."""
        def op() -> SessionState:
            row = self._get_row(turn.task_id)
            if row["session_id"] is not None and row["session_id"] != turn.session_id:
                raise SessionInvariantError(
                    f"turn for task {turn.task_id} used session {turn.session_id}, expected {row['session_id']}"
                )
            usage = TokenUsage.model_validate_json(row["token_usage"]).add(turn.usage)
            self._conn.execute("BEGIN")
            try:
                self._conn.execute(
                    "INSERT INTO turns (task_id, turn_index, payload, created_at) VALUES (?,?,?,?)",
                    (turn.task_id, turn.turn_index, turn.model_dump_json(), turn.created_at.isoformat()),
                )
                self._conn.execute(
                    "UPDATE sessions SET turn_count=turn_count+1, token_usage=?, total_cost_usd=total_cost_usd+?,"
                    " updated_at=? WHERE task_id=?",
                    (usage.model_dump_json(), turn.cost_usd or 0.0, utcnow().isoformat(), turn.task_id),
                )
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise
            return self._row_to_state(self._get_row(turn.task_id))
        return await self._run(op)

    async def turns(self, task_id: str) -> list[TurnRecord]:
        def op() -> list[TurnRecord]:
            rows = self._conn.execute(
                "SELECT payload FROM turns WHERE task_id=? ORDER BY turn_index", (task_id,)
            ).fetchall()
            return [TurnRecord.model_validate_json(r["payload"]) for r in rows]
        return await self._run(op)

    # ------------------------------------------------------------------ events
    async def add_event(self, event: TaskEvent) -> TaskEvent:
        def op() -> TaskEvent:
            row = self._conn.execute(
                "SELECT COALESCE(MAX(seq), 0) AS m FROM events WHERE task_id=?", (event.task_id,)
            ).fetchone()
            ev = event.model_copy(update={"seq": row["m"] + 1})
            self._conn.execute(
                "INSERT INTO events (task_id, seq, payload) VALUES (?,?,?)", (ev.task_id, ev.seq, ev.model_dump_json())
            )
            return ev
        return await self._run(op)

    async def events(self, task_id: str, after_seq: int = 0) -> list[TaskEvent]:
        def op() -> list[TaskEvent]:
            rows = self._conn.execute(
                "SELECT payload FROM events WHERE task_id=? AND seq>? ORDER BY seq", (task_id, after_seq)
            ).fetchall()
            return [TaskEvent.model_validate_json(r["payload"]) for r in rows]
        return await self._run(op)

    # ------------------------------------------------------------------ summary
    async def set_summary(self, summary: FinalSummary) -> None:
        def op() -> None:
            self._conn.execute(
                "UPDATE sessions SET summary=?, updated_at=? WHERE task_id=?",
                (summary.model_dump_json(), utcnow().isoformat(), summary.task_id),
            )
        await self._run(op)

    async def get_summary(self, task_id: str) -> FinalSummary | None:
        def op() -> FinalSummary | None:
            row = self._get_row(task_id)
            return FinalSummary.model_validate_json(row["summary"]) if row["summary"] else None
        return await self._run(op)

    async def raw(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        """Read-only helper for diagnostics/tests."""
        def op() -> list[dict[str, Any]]:
            return [dict(r) for r in self._conn.execute(sql, params).fetchall()]
        return await self._run(op)

