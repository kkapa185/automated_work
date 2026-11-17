"""Benchmark runner: drive the orchestrator on ticket-style specs and score the results with hidden harnesses.

Each benchmark lives in ``benchmarks/<name>/``:

    task.md       the ticket the system sees (what to build - never how the reference does it)
    prepare.py    optional: ``--workspace W --reference R`` copies input data into the empty workspace
    compare.py    hidden acceptance harness: ``--app W --reference R --out result.json``; it runs the
                  generated application and the reference on the same inputs and writes
                  {"score": 0..1, "checks": [{"name", "passed", "detail"}], ...}

``benchmarks/manifest.json`` lists them. Usage::

    python benchmarks/runner.py run [--only NAME ...] [--force]   # resumable; skips finished ones
    python benchmarks/runner.py compare NAME [--attempt N]          # re-score an existing workspace
    python benchmarks/runner.py status

State (database, workspaces, logs) lives in $BENCH_STATE (default /home/user/bench_state) so a crashed or
restarted runner resumes the in-flight task on its existing claude session. Usage-limit pauses are handled
by the orchestrator itself.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config import Settings  # noqa: E402
from orchestrator import TaskOrchestrator  # noqa: E402
from registry import SessionRegistry, TaskNotFoundError  # noqa: E402
from schemas import TaskInput, TaskStatus  # noqa: E402

BENCH_DIR = ROOT / "benchmarks"
STATE = Path(os.environ.get("BENCH_STATE", "/home/user/bench_state"))
RESULTS = BENCH_DIR / "results.jsonl"
COPY_EXCLUDE = {".git", ".venv", "venv", "env", "node_modules", "__pycache__", ".pytest_cache", ".mypy_cache",
                "target", "dist", "build", ".next", ".cache", ".tox", "weights", "checkpoints", ".ruff_cache"}
MAX_COPY_FILE_BYTES = 2_000_000

log = logging.getLogger("bench")

DEFAULT_CONSTRAINT = (
    "Build this from the specification. Do not clone, download, open or search for the reference project "
    "{repo} (or forks, mirrors or derivatives of it); do not copy its code."
)


def load_manifest() -> list[dict[str, Any]]:
    return json.loads((BENCH_DIR / "manifest.json").read_text())["benchmarks"]


def load_state() -> dict[str, Any]:
    """One state file per benchmark so several runner processes can work in parallel without races."""
    d = STATE / "state"
    return {p.stem: json.loads(p.read_text()) for p in d.glob("*.json")} if d.exists() else {}


def save_state(st: dict[str, Any]) -> None:
    d = STATE / "state"
    d.mkdir(parents=True, exist_ok=True)
    for name, entry in st.items():
        tmp = d / f"{name}.json.tmp"
        tmp.write_text(json.dumps(entry, indent=2))
        tmp.replace(d / f"{name}.json")


def finished_names() -> set[str]:
    if not RESULTS.exists():
        return set()
    return {json.loads(line)["name"] for line in RESULTS.read_text().splitlines() if line.strip()}


def settings_for(bench: dict[str, Any]) -> Settings:
    overrides: dict[str, Any] = {"db_path": STATE / "orchestrator.db", "workspace_root": STATE / "ws"}
    if bench.get("model"):
        overrides["model"] = bench["model"]
    if bench.get("cli_timeout_s"):
        overrides["cli_timeout_s"] = bench["cli_timeout_s"]
    if bench.get("verify_timeout_s"):
        overrides["verify_timeout_s"] = bench["verify_timeout_s"]
    return Settings.from_env(**overrides)


def copy_app(src: Path, dst: Path, inputs: list[str] | None = None) -> None:
    """Copy the generated application, minus build artefacts, large files and the benchmark's input data."""
    if dst.exists():
        shutil.rmtree(dst)
    input_set = set(inputs or [])

    def ignore(d: str, names: list[str]) -> set[str]:
        skipped = {n for n in names if n in COPY_EXCLUDE or n.endswith((".pyc", ".h5", ".hdf5", ".keras", ".pt", ".ckpt"))}
        if Path(d) == src:
            skipped |= {n for n in names if n in input_set or n.startswith("_bench")}
        for n in names:
            p = Path(d) / n
            if p.is_file() and p.stat().st_size > MAX_COPY_FILE_BYTES:
                skipped.add(n)
        return skipped

    shutil.copytree(src, dst, ignore=ignore, symlinks=True)


def run_compare(bench: dict[str, Any], workspace: Path, attempt: int) -> dict[str, Any]:
    out = STATE / "results" / bench["name"] / f"attempt{attempt}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    cmp = BENCH_DIR / bench["name"] / "compare.py"
    ref = bench.get("reference_path", "")
    t0 = time.time()
    proc = subprocess.run(
        [sys.executable, str(cmp), "--app", str(workspace), "--reference", ref, "--out", str(out)],
        capture_output=True, text=True, timeout=bench.get("compare_timeout_s", 7200),
    )
    (out.parent / f"attempt{attempt}.compare.log").write_text(proc.stdout + "\n--- stderr ---\n" + proc.stderr)
    if out.exists():
        res = json.loads(out.read_text())
    else:
        res = {"score": 0.0, "checks": [], "error": f"compare.py exited {proc.returncode}: {proc.stderr[-2000:]}"}
    res["compare_seconds"] = round(time.time() - t0, 1)
    return res


async def run_one(bench: dict[str, Any], force: bool) -> dict[str, Any]:
    name = bench["name"]
    st = load_state()
    entry = st.get(name, {"attempt": 0})
    settings = settings_for(bench)
    registry = SessionRegistry(settings.db_path)
    orch = TaskOrchestrator(settings, registry)
    try:
        task_id = entry.get("task_id")
        # An in-flight (non-terminal) task is ALWAYS resumed on its stored session, even with --force:
        # starting a new attempt would orphan a live claude session. --force only re-runs finished ones.
        resumable = await in_flight(registry, task_id)
        if resumable:
            log.info("%s: resuming task %s", name, task_id)
            workspace = Path(entry["workspace"])
            paused = await registry.get(task_id)
            if paused.resume_at:
                orch.gate.block(paused.resume_at)  # arm the usage gate before the task's next turn
            orch.start(task_id)
        else:
            entry["attempt"] = entry.get("attempt", 0) + 1
            workspace = STATE / "ws" / f"{name}-{entry['attempt']}"
            if workspace.exists():
                shutil.rmtree(workspace)
            workspace.mkdir(parents=True)
            prep = BENCH_DIR / name / "prepare.py"
            if prep.exists():
                subprocess.run([sys.executable, str(prep), "--workspace", str(workspace),
                                "--reference", bench.get("reference_path", "")], check=True)
            entry["inputs"] = sorted(p.name for p in workspace.iterdir())  # provided data, not generated code
            constraints = [DEFAULT_CONSTRAINT.format(repo=bench["reference_repo"])] if bench.get("reference_repo") else []
            constraints += bench.get("constraints", [])
            task = TaskInput(
                description=(BENCH_DIR / name / "task.md").read_text(),
                workspace_path=str(workspace),
                max_turns=bench.get("max_turns"),
                constraints=constraints,
                auto_detect_sources=False,
            )
            state = await orch.submit(task, start=False)
            task_id = state.task_id
            entry.update({"task_id": task_id, "workspace": str(workspace), "started_at": time.time(), "done": False})
            save_state({name: entry})
            orch.start(task_id)
        summary = await orch.wait(task_id)
        assert summary is not None
        log.info("%s: orchestrator finished %s in %d turns ($%.2f)", name, summary.status.value,
                 summary.turns_used, summary.total_cost_usd)
        compare = run_compare(bench, workspace, entry["attempt"])
        copy_app(workspace, BENCH_DIR / name / "app", entry.get("inputs"))
        record = {
            "name": name, "attempt": entry["attempt"], "task_id": task_id, "session_id": summary.session_id,
            "status": summary.status.value, "turns": summary.turns_used, "cost_usd": round(summary.total_cost_usd, 4),
            "review_verdict": summary.review_verdict, "failure_reason": summary.failure_reason,
            "score": compare.get("score"), "checks": compare.get("checks"), "compare_error": compare.get("error"),
            "wall_seconds": round(time.time() - entry.get("started_at", time.time()), 1),
            "system_version": git_rev(),
        }
        with RESULTS.open("a") as fh:
            fh.write(json.dumps(record) + "\n")
        entry["done"] = True
        save_state({name: entry})
        return record
    finally:
        await orch.shutdown()
        registry.close()


async def in_flight(registry: SessionRegistry, task_id: str | None) -> bool:
    if not task_id:
        return False
    try:
        return not (await registry.get(task_id)).status.is_terminal
    except TaskNotFoundError:
        return False


async def pending_work(force_names: set[str] | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(in-flight benchmarks to resume, not-yet-run benchmarks to start), in manifest order."""
    benches = [b for b in load_manifest() if b.get("enabled", True)]
    st, done = load_state(), finished_names()
    db = STATE / "orchestrator.db"
    reg = SessionRegistry(db) if db.exists() else None
    resume, start = [], []
    try:
        for b in benches:
            tid = st.get(b["name"], {}).get("task_id")
            if reg is not None and await in_flight(reg, tid):
                resume.append(b)
            elif b["name"] not in done or b["name"] in (force_names or set()):
                start.append(b)
    finally:
        if reg is not None:
            reg.close()
    return resume, start


def git_rev() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True,
                              text=True).stdout.strip()
    except OSError:
        return "unknown"


async def cmd_run(args: argparse.Namespace) -> int:
    benches = [b for b in load_manifest() if b.get("enabled", True)]
    if args.only:
        benches = [b for b in benches if b["name"] in args.only]
    resume, _ = await pending_work()
    resume_names = {b["name"] for b in resume}
    done = finished_names()
    for b in benches:
        if b["name"] in done and b["name"] not in resume_names and not args.force:
            log.info("%s: already finished, skipping (use --force)", b["name"])
            continue
        rec = await run_one(b, args.force)
        log.info("%s: score=%s status=%s", b["name"], rec["score"], rec["status"])
    return 0


async def cmd_daemon(args: argparse.Namespace) -> int:
    """Idempotent supervisor: resume every in-flight benchmark, then start pending ones, N at a time.

    Each benchmark runs in its own subprocess (`runner.py run --only NAME`), so one crashing run cannot take
    the others down. Relaunching the daemon after a crash, container restart or usage-limit pause is safe:
    in-flight tasks continue on their stored claude sessions and finished ones are skipped.
    """
    resume, start = await pending_work()
    queue = resume + [b for b in start if not args.only or b["name"] in args.only]
    log.info("daemon: resuming %s; then starting %s", [b["name"] for b in resume],
             [b["name"] for b in queue[len(resume):]])
    running: dict[str, asyncio.subprocess.Process] = {}
    logs = STATE / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    while queue or running:
        while queue and len(running) < args.parallel:
            b = queue.pop(0)
            fh = open(logs / f"{b['name']}.log", "a")
            running[b["name"]] = await asyncio.create_subprocess_exec(
                sys.executable, str(Path(__file__).resolve()), "run", "--only", b["name"],
                stdout=fh, stderr=asyncio.subprocess.STDOUT, cwd=str(ROOT))
            fh.close()
            log.info("daemon: started %s (pid %s)", b["name"], running[b["name"]].pid)
        await asyncio.sleep(10)
        for name, proc in list(running.items()):
            if proc.returncode is not None:
                log.info("daemon: %s exited with %s", name, proc.returncode)
                del running[name]
    log.info("daemon: all benchmarks finished")
    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    bench = next(b for b in load_manifest() if b["name"] == args.name)
    st = load_state().get(args.name, {})
    attempt = args.attempt or st.get("attempt", 1)
    ws = Path(args.workspace) if args.workspace else STATE / "ws" / f"{args.name}-{attempt}"
    print(json.dumps(run_compare(bench, ws, attempt), indent=2))
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    st = load_state()
    reg = SessionRegistry(STATE / "orchestrator.db") if (STATE / "orchestrator.db").exists() else None
    for b in load_manifest():
        e = st.get(b["name"], {})
        line = f"{b['name']:<28} attempt={e.get('attempt', 0)} done={e.get('done', False)}"
        if reg and e.get("task_id"):
            try:
                s = asyncio.run(reg.get(e["task_id"]))
                line += f" status={s.status.value} turns={s.turn_count} cost=${s.total_cost_usd:.2f}"
                if s.resume_at:
                    line += f" resume_at={s.resume_at.isoformat()}"
            except TaskNotFoundError:
                pass
        print(line)
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--only", nargs="*")
    r.add_argument("--force", action="store_true")
    c = sub.add_parser("compare")
    c.add_argument("name")
    c.add_argument("--attempt", type=int)
    c.add_argument("--workspace")
    sub.add_parser("status")
    dm = sub.add_parser("daemon")
    dm.add_argument("--parallel", type=int, default=4)
    dm.add_argument("--only", nargs="*")
    args = p.parse_args()
    STATE.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        handlers=[logging.StreamHandler()])
    if args.cmd == "run":
        return asyncio.run(cmd_run(args))
    if args.cmd == "compare":
        return cmd_compare(args)
    if args.cmd == "daemon":
        return asyncio.run(cmd_daemon(args))
    return cmd_status(args)


if __name__ == "__main__":
    sys.exit(main())
