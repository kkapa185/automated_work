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
""" + "\n".join(rows) + "\n"
(B / "README.md").write_text(text)
print(text)
