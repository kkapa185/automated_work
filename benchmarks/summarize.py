"""Render benchmarks/README.md from manifest.json + results.jsonl (latest attempt per benchmark)."""
import json
from pathlib import Path

B = Path(__file__).resolve().parent
manifest = json.loads((B / "manifest.json").read_text())["benchmarks"]
results = {}
if (B / "results.jsonl").exists():
    for line in (B / "results.jsonl").read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            results.setdefault(r["name"], []).append(r)

rows = []
for b in manifest:
    rs = results.get(b["name"], [])
    hist = " → ".join(f"{r['score']:.2f}" for r in rs if r.get("score") is not None) or "–"
    last = rs[-1] if rs else None
    passed = f"{sum(c['passed'] for c in last['checks'])}/{len(last['checks'])}" if last and last.get("checks") else "–"
    rows.append(f"| [{b['name']}]({b['name']}/report.md) | [{b['reference_repo'].split('github.com/')[1]}]({b['reference_repo']}) | "
                f"{last['status'] if last else 'not run'} | {hist} | {passed} | {last['turns'] if last else '–'} | "
                f"{'$%.2f' % last['cost_usd'] if last else '–'} |")
text = f"""# Benchmarks: real GitHub projects rebuilt from a ticket

Each benchmark directory holds:
* `task.md`: the ticket the orchestrator receives. It describes *what* to build, never the reference code.
* `prepare.py` (optional): copies input data that a real user would hand over (datasets, source to assemble, API spec).
* `compare.py`: the hidden acceptance harness. It runs the **reference project** and the **generated
  application** on the same inputs and scores agreement. The orchestrator never sees it.
* `app/`: the final generated application (no dependencies, build output or input data).
* `report.md`: the analysis, plus any system changes the benchmark triggered.

Run with `python benchmarks/runner.py run [--only NAME]`; it is resumable and survives usage-limit pauses.
`python benchmarks/summarize.py` regenerates this table.

| benchmark | reference | status | score history | checks passed (last) | turns | cost |
|---|---|---|---|---|---|---|
""" + "\n".join(rows) + "\n" + """
## System improvements triggered by these benchmarks
All of these are generic and none is specific to a project. Each has tests in `tests/`.

| trigger | problem found | fix |
|---|---|---|
| first real-CLI runs | nested CLI loaded the account's MCP connectors (Slack/Jira/...) on every turn | `--strict-mcp-config` (`cli_isolate_mcp`) |
| design review | a first turn that timed out before printing JSON would be retried as a *new* session | pre-assigned `--session-id`, persisted before the call; "already in use" → adopt and resume |
| Apollo-11 (30+ min turns) | no progress visible during long turns | workspace-activity `heartbeat` events |
| 5-hour limit hit at 13:34 | (worked) all six tasks paused, persisted `resume_at`, shared gate | — |
| worker restart during the pause | runner processes died; `--force` would have re-attempted in-flight tasks | always resume in-flight tasks; idempotent `runner.py daemon`; stale pause records cleared |
| usage-limit test | "resets 3pm" was parsed against the wall clock, not the orchestrator clock | parse relative to the injected clock |
| itsdangerous attempt 2 | model memory of a similar tool overrode the spec (an undocumented `key_derivation="hmac"` default); self-derived test vectors hid it | prompts: ticket/docs are normative, no undocumented defaults, examples become exact tests, known-answer vectors are derived from the definition; review re-checks every default |
| cost reporting | the CLI's `total_cost_usd` is cumulative per session; summing it overstated cost ~3x | per-turn deltas (`turn_cost`), `runner.py fix-costs` |
| MATLAB hub | 81 MB of benchmark input data copied into the committed app | runner excludes the prepared inputs |
| round 3 (large apps) | single implement turns of 1 h+ with no intermediate verification | **milestone mode**: plan writes `.orchestrator/milestones.json`; one implement turn per milestone, a cumulative gate and bounded heals per milestone, turn budget scaled by milestones; resumable per milestone |
| chess engine (round 3) | a usage-limit pause *during the plan turn* left a bound session with no plan; resume skipped hydration and planning | planning completion is decided from the turn history; an interrupted plan turn is re-sent to the same session |
| cmark (round 3) | linear-time requirement met in general, but the system's tests missed worst-case shapes (deeply nested lists) | prompt rule: timed benchmark tests at the stated sizes on worst-case inputs |

Several low first-attempt scores (Pascal, itsdangerous, slugify, jsmn, hexyl) came from **inaccurate or
ambiguous tickets that I wrote**, not from the system: it followed them exactly. Each such case is
documented in its report, along with the corrected ticket and the rerun.
"""
(B / "README.md").write_text(text)
print(text)
