# Claude Task Orchestrator

A FastAPI + Pydantic v2 + asyncio service that takes a high-level engineering task (build an app, fix a bug,
implement a Jira ticket, follow a Confluence spec), gathers the context it needs, and completes the task with the
`claude` CLI. Each task uses **exactly one** CLI session, driven through
**Plan → Implement → Verify → Self-heal** until every verification command exits `0` or the turn budget runs out.

## Single-session invariant

| Turn | Command |
|------|---------|
| first (plan) | `claude -p "<context + plan prompt>" --output-format json --allowedTools ... --permission-mode ...` |
| every later turn | `claude --resume <session_id> -p "<feedback>" --output-format json ...` |

* `task_id` (UUIDv4) maps to one row in SQLite (`registry.py`). `session_id` is bound **once**, as soon as the first
  JSON reply is parsed. If the reply is a transient error, the session is still bound, so the retry resumes it
  instead of starting a second one.
* A reply that carries a different `session_id` raises `SessionInvariantError` and fails the task. A session id
  can never belong to two tasks (enforced by a `UNIQUE` constraint).
* Turns of one task are serialized with a per-task lock. `start()` returns the existing asyncio task if one is
  already running.
* After a restart, non-terminal tasks resume on their stored session: the next step is verification, or the
  implement step if only the plan turn finished.

## Execution loop (`orchestrator.py`)

1. **HYDRATING**: detect and fetch sources concurrently: Jira keys/URLs, Confluence pages, local files and
   directories (including paths named in stack traces), `git diff`, and web URLs. Results are compiled into an
   XML-tagged payload (`<task_request>`, `<context><artifact …>`). A source that fails is listed under
   `<unavailable_sources>`; it never aborts the task.
2. **PLANNING** (turn 1): inspect the workspace and output a plan.
3. **IMPLEMENTING** (turn 2): implement the change and write comprehensive tests.
4. **VERIFYING**: the orchestrator runs the checks itself, without a shell, under a timeout and with
   process-group cleanup. It uses `verification_commands` when given, otherwise it detects them: pytest,
   npm lint/build/test, cargo, go, or `make test`. If no checks are found, verification fails and Claude is told
   to add tests.
5. **HEALING**: the exact failing commands, exit codes and stdout/stderr tails go back to the same session, then
   verification runs again.
6. **COMPLETED** only when all exit codes are 0. **FAILED** on `max_turns_exhausted`, a fatal CLI error, or an
   invariant violation. **CANCELLED** through the API.

Transient CLI failures (timeouts, 429/529 overload, network errors, garbled output) are retried with
full-jitter exponential backoff. Retries do not use up `max_turns`. Fatal errors (auth, missing binary) are not
retried. On timeout or cancellation the CLI's whole process group gets SIGTERM, then SIGKILL, and is reaped, so
no zombie processes are left.

## Layout

```
config.py          Settings (ORCH_* env vars; JIRA_* / CONFLUENCE_* aliases)
schemas.py         Pydantic models: TaskInput, SessionState, ClaudeCLIResult, VerificationReport, FinalSummary, ...
connectors/        jira.py, confluence.py (+ html.py storage-format→Markdown), local.py (file/git/url/text), compiler.py
registry.py        SQLite session registry (sessions, turns, events)
process.py         async subprocess runner (streaming, timeouts, process-group kill)
claude_session.py  ClaudeSessionManager (-p / --resume / --output-format json, retries, invariant checks)
verification.py    VerificationRunner + auto-detection
prompts.py         phase prompts
orchestrator.py    TaskOrchestrator state machine + EventBus
main.py            FastAPI app + CLI
tests/             pytest suite using a scripted fake `claude` binary (tests/fake_claude.py)
```

## Running

```bash
pip install -r requirements.txt
```

```bash
python main.py serve --port 8000
```

```bash
curl -X POST localhost:8000/tasks -H 'content-type: application/json' \
  -d '{"description": "Implement PROJ-123", "workspace_path": "/path/to/repo", "verification_commands": ["pytest -q"]}'
```

```bash
curl -N localhost:8000/tasks/<task_id>/events
```

```bash
python main.py run "Fix the crash in https://acme.atlassian.net/browse/PROJ-9" --workspace ./repo --verify "pytest -q" -v
```

```bash
python main.py status <task_id> --turns
```

Endpoints: `POST /tasks`, `GET /tasks`, `GET /tasks/{id}`, `GET /tasks/{id}/turns`, `GET /tasks/{id}/summary`,
`GET /tasks/{id}/events` (SSE, `?after=<seq>&include_output=false`), `POST /tasks/{id}/cancel`,
`POST /tasks/{id}/resume`, `GET /healthz`.

### Key settings

| Variable | Default | Meaning |
|----------|---------|---------|
| `ORCH_CLAUDE_BINARY` | `claude` | CLI to execute |
| `ORCH_MAX_TURNS` | `5` | turn budget per task (plan + implement + heals) |
| `ORCH_CLI_TIMEOUT_S` / `ORCH_VERIFY_TIMEOUT_S` | `1800` / `900` | per-invocation timeouts |
| `ORCH_MAX_TRANSIENT_RETRIES` | `3` | retries per turn for transient errors |
| `ORCH_ALLOWED_TOOLS_STANDARD` | `Bash,Edit,Write,Read,Glob,Grep` | `--allowedTools` for `safety=standard` |
| `ORCH_ALLOWED_TOOLS_SAFE` | `Read,Glob,Grep` | `safety=read_only` (other tools are added to `--disallowedTools`) |
| `ORCH_PERMISSION_MODE` | `acceptEdits` | `--permission-mode` (`none` to omit) |
| `ORCH_WORKSPACE_ROOT` / `ORCH_DB_PATH` | `/tmp/workspaces` / `./orchestrator.db` | storage |
| `JIRA_BASE_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN` | – | Cloud basic auth (omit the email to use a Server/DC bearer PAT) |
| `ORCH_JIRA_API_VERSION`, `ORCH_JIRA_ACCEPTANCE_CRITERIA_FIELD` | `2`, – | v3 ADF support; custom AC field id |
| `CONFLUENCE_BASE_URL`, `CONFLUENCE_EMAIL`, `CONFLUENCE_API_TOKEN` | – | Confluence REST |

Prompts larger than `ORCH_MAX_ARGV_PROMPT_BYTES` (100 KB) are sent to `claude -p` over stdin, because Linux
limits a single argv entry to 128 KiB.

## Tests

```bash
python -m pytest -q
```

The suite runs the real subprocess path against `tests/fake_claude.py`, a scriptable stand-in for the CLI that
logs every argv. It checks that every retry, self-healing and post-restart turn reuses the same `session_id`. It
also covers the budget, transient vs fatal errors, timeouts with no zombies, cancellation, safety-based tool
lists, stdin prompts, the connectors (Jira v2/v3 ADF, Confluence macros, retry on 429, git diff, URLs),
verification auto-detection, the registry, the HTTP API and SSE, and the CLI.
