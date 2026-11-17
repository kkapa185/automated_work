# Benchmark report — mathworks/MATLAB-Simulink-Challenge-Project-Hub

**Ticket:** [`task.md`](task.md) (HUB-77). The system received the hub's Markdown content (`README.md`,
`megatrends/`, `projects/*/README.md`) **without** the repo's curated `projects/projects.json` and
`table.html` Project Explorer, which are the expected outputs.

**Reference execution:** the hub's own `projects.json` (83 curated project records) and its explorer's
filter semantics. The hidden harness [`compare.py`](compare.py):
- builds the catalog with `./catalog build`;
- compares the fields per project id;
- starts `./catalog serve` and checks the API filters, facets and 404s;
- drives the explorer UI headlessly with Playwright: one card per project, `?difficulty=` URL state, and the search box.

## Result (attempt 1, system `d8b43d5`): score 0.95 (21/22)
| field (mean agreement with the curated JSON) | value |
|---|---|
| ids (recall / precision) | 1.00 / 1.00 (83/83) |
| title | 0.99 |
| technology_trends | 0.94 |
| expertise_gained | 0.95 |
| platforms | 0.98 |
| partners | 0.95 |
| products | 0.79 |
| hardware_required | 0.83 |
| difficulty | 0.77 |
| project_type / application_areas (subjective) | 0.64 / 0.66 |

The API, facets, 404 handling, explorer rendering (83 cards), URL state and search all pass.

**The one failing check:** the combined filter "Robotics & Advanced" returns 4 projects where the
reference returns 12. The generated rule (base level from the stated academic levels, ±1 for
scope signals) rates fewer projects *Advanced* (21) than the curated data (30). The curated labels
are not a function of the page text: identical level strings map to different difficulties. So this
reflects an underspecified judgement field, not a defect. The rule is deterministic and documented, as
the ticket asked.

**Process:** 4 turns on one session (`a64d4880…`): plan → implement → review (GAPS_FIXED) → review (PASS). $4.74, 10 min.

**System changes triggered:**
- The runner no longer copies the benchmark's 81 MB input data into `app/`; it snapshots the prepared
  inputs and excludes them.
