# Benchmarks: real GitHub projects rebuilt from a ticket

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
| [crypto_price_prediction](crypto_price_prediction/report.md) | [khuangaf/CryptocurrencyPrediction](https://github.com/khuangaf/CryptocurrencyPrediction) | COMPLETED | 1.00 | 20/20 | 4 | $0.47 |
| [matlab_challenge_explorer](matlab_challenge_explorer/report.md) | [mathworks/MATLAB-Simulink-Challenge-Project-Hub](https://github.com/mathworks/MATLAB-Simulink-Challenge-Project-Hub) | COMPLETED | 0.95 | 21/22 | 4 | $1.55 |
| [apollo11_agc_assembler](apollo11_agc_assembler/report.md) | [chrislgarry/Apollo-11](https://github.com/chrislgarry/Apollo-11) | COMPLETED | 0.98 | 6/8 | 4 | $11.27 |
| [micrograd_autograd](micrograd_autograd/report.md) | [karpathy/micrograd](https://github.com/karpathy/micrograd) | COMPLETED | 1.00 | 7/7 | 4 | $0.44 |
| [minbpe_tokenizer](minbpe_tokenizer/report.md) | [karpathy/minbpe](https://github.com/karpathy/minbpe) | COMPLETED | 1.00 | 16/16 | 4 | $0.36 |
| [pascal_interpreter](pascal_interpreter/report.md) | [rspivak/lsbasi](https://github.com/rspivak/lsbasi) | COMPLETED | 0.74 → 0.85 → 1.00 | 40/40 | 3 | $0.53 |
| [itsdangerous_signing](itsdangerous_signing/report.md) | [pallets/itsdangerous](https://github.com/pallets/itsdangerous) | COMPLETED | 0.96 → 0.71 → 1.00 | 52/52 | 4 | $0.68 |
| [slugify_js](slugify_js/report.md) | [sindresorhus/slugify](https://github.com/sindresorhus/slugify) | COMPLETED | 0.55 → 0.61 | 54/89 | 3 | $0.63 |
| [jsmn_c](jsmn_c/report.md) | [zserge/jsmn](https://github.com/zserge/jsmn) | COMPLETED | 0.64 → 1.00 | 15/15 | 4 | $0.80 |
| [hexyl_rust](hexyl_rust/report.md) | [sharkdp/hexyl](https://github.com/sharkdp/hexyl) | COMPLETED | 0.29 → 0.35 | 11/31 | 4 | $0.89 |
| [hey_go](hey_go/report.md) | [rakyll/hey](https://github.com/rakyll/hey) | COMPLETED | 0.96 | 65/68 | 3 | $0.53 |
| [realworld_api](realworld_api/report.md) | [gothinkster/realworld](https://github.com/gothinkster/realworld) | COMPLETED | 0.99 | 157/158 | 4 | $0.65 |
| [todomvc_frontend](todomvc_frontend/report.md) | [tastejs/todomvc](https://github.com/tastejs/todomvc) | COMPLETED | 1.00 | 31/31 | 4 | $0.48 |
| [jq_clone](jq_clone/report.md) | [jqlang/jq](https://github.com/jqlang/jq) | COMPLETED | 0.67 | 16/24 | 5 | $4.79 |
| [commonmark_renderer](commonmark_renderer/report.md) | [commonmark/cmark](https://github.com/commonmark/cmark) | COMPLETED | 0.79 | 11/14 | 4 | $2.05 |
| [mal_lisp](mal_lisp/report.md) | [kanaka/mal](https://github.com/kanaka/mal) | COMPLETED | 1.00 | 25/25 | 8 | $3.88 |
| [lua_interpreter](lua_interpreter/report.md) | [lua/lua](https://github.com/lua/lua) | COMPLETED | 0.38 → 0.38 | 13/34 | 9 | $14.47 |
| [sql_database](sql_database/report.md) | [sqlite/sqlite](https://github.com/sqlite/sqlite) | COMPLETED | 0.91 | 21/23 | 6 | $5.83 |
| [redis_server](redis_server/report.md) | [redis/redis](https://github.com/redis/redis) | COMPLETED | 1.00 | 164/164 | 8 | $6.26 |
| [git_vcs](git_vcs/report.md) | [git/git](https://github.com/git/git) | COMPLETED | 1.00 | 85/85 | 7 | $15.20 |
| [chess_engine](chess_engine/report.md) | [official-stockfish/Stockfish](https://github.com/official-stockfish/Stockfish) | COMPLETED | 1.00 | 28/28 | 5 | $1.67 |
| [json_rest_server](json_rest_server/report.md) | [typicode/json-server](https://github.com/typicode/json-server) | COMPLETED | 0.76 → 0.98 | 48/49 | 4 | $1.08 |
| [nanogpt_training](nanogpt_training/report.md) | [karpathy/nanoGPT](https://github.com/karpathy/nanoGPT) | COMPLETED | 1.00 | 13/13 | 4 | $0.52 |

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
