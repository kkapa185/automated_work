# Challenge Project catalog + Project Explorer

Turns the MATLAB & Simulink Challenge Project Hub content snapshot in `hub/` into a structured,
searchable catalog (`projects.json`) and serves an interactive **Project Explorer** (JSON API + single-page UI).
Pure Python 3.10+ standard library at runtime; `pytest` is the only dev dependency. No network access is needed.

## Install, run, test
```bash
python3 -m pip install -r requirements-dev.txt        # only needed for the tests
./catalog build hub -o out/projects.json               # write the catalog (83 projects)
./catalog serve hub --port 8000                        # http://127.0.0.1:8000/  (--host to change interface)
python3 -m pytest                                      # full suite (node, if present, runs the UI script against the live API)
```
`serve` builds the catalog in memory at start-up. `build` exits with status 2 if the hub has no `projects/` directory.

## What is a project?
A folder `hub/projects/<Folder>/` that contains a `README.md`. `ALL_SUBMISSIONS.md`, `submissions.md`, folders without a README
(e.g. a submissions-only duplicate), `Classroom Challenge Projects/` and the top-level README are ignored.
Output is sorted by numeric `id`, then title, and is byte-for-byte deterministic.

## Extraction rules (all deterministic; the rule tables live in `catalog_explorer/rules.py`)
| field | rule |
|---|---|
| `id` | `## Project Number` section (digits); fallback `tfa_2=` of the sign-up link. No id → project skipped with a warning. |
| `title` | `<h1>` of the header table (tags stripped, entities unescaped); fallback first `# ` heading, then folder name. |
| `project_url` / `source_file` | `https://github.com/mathworks/MATLAB-Simulink-Challenge-Project-Hub/tree/main/projects/<url-quoted folder>` / `projects/<folder>/README.md`. |
| `summary` | first `<p>` after the `<h1>`, reduced to its first sentence (abbreviations like "e.g." do not end a sentence); fallback first paragraph of `## Project Description`. |
| `thumbnail` | first `<img src>` before the first `##` heading (the header image). |
| `technology_trends` | names (file stems) of `megatrends/*.md` pages linking to the project (`href` or Markdown link containing `projects/<folder>`, URL-decoded, parentheses allowed). Matching is by folder name, falling back to a normalised key (case/punctuation-insensitive, Modelling≡Modeling). |
| `expertise_gained_original` | `## Expertise Gained` split on commas, semicolons, bullets, newlines; trimmed, whitespace-collapsed, case-insensitively de-duplicated (first spelling/order kept). |
| `academic_levels` | `## Project Difficulty`: Bachelor / Master's (`Master’s`, "Master's level") / Doctoral, canonical spelling, ordered Bachelor < Master's < Doctoral. |
| `difficulty` | **Base** from levels: only Bachelor → Beginner; Doctoral without Bachelor → Advanced; everything else (Master's, Bachelor+Master's, all three, none stated) → Intermediate. **Scope adjustment (±1 step max):** up if the difficulty text says advanced / research-level / state-of-the-art / PhD, or if the project has ≥6 "Advanced project work" items *and* required hardware, or if it is Bachelor-level but needs required hardware; down if "beginner / introductory / entry-level / getting started" appears. Up and down cancel. |
| `mathworks_products` | Union of (a) product names/aliases in the page (word-boundary regex table, e.g. "Machine Learning Toolbox" → *Statistics and Machine Learning Toolbox*, "Econometric Toolbox" → *Econometrics Toolbox*), (b) `mathworks.com/products/<slug>` links, (c) `mathworks.com/help/<docroot>/` links (e.g. `physmod`→Simscape, `nav`→Navigation Toolbox). MATLAB and Simulink themselves are platforms, not products. Sorted. |
| `mathworks_platforms` | *Simulink* if "Simulink" appears in prose (URLs removed) or a Simulink-family product is used (Simscape*, Stateflow, Powertrain/Vehicle Dynamics/Aerospace/Motor Control Blockset, …); *MATLAB* if "MATLAB" appears in prose or any toolbox outside that family is used; default MATLAB. |
| `project_type`, `application_areas` | Keyword rule tables (regex + weight per label). Each label scores `weight × (1.5 × min(hits,2) in title/summary/expertise/impact + 0.25 × min(hits,4) in the rest of the page)`; megatrend membership (`TREND_TO_AREA`, +3) and used products (`PRODUCT_TO_TYPE`/`PRODUCT_TO_AREA`, +1) add evidence. A label is assigned at score ≥ 3 (at most 4 types / 3 areas, strongest kept; canonical order). If nothing qualifies the best-scoring label (else *System Design* / *Education / Research*) is used, so lists are never empty. |
| `hardware_required` | **Required**: non-trivial `## Required Hardware` section, or phrases such as "must be implemented on", "hardware is required", "requires … board/kit/robot". **Optional**: any hardware tag, or hardware-in-the-loop / deploy-to-hardware / real-hardware / FPGA phrases. Else **None**. |
| `hardware_tags` | Dictionary of boards, robots, SDRs, motor drivers, … (word-boundary regexes, canonical names). Generic sensors (IMU, LiDAR, GPS, camera, microphone, …) only count in a sentence that also has a "real hardware" cue (connect, mount, onboard, deploy, board, …), so simulated sensors are not hardware. |
| `has_partner`, `partners`, `partner_type` | Names from "developed in collaboration with **X**" plus logo links in an *Industry Partner* block (domain → company table, else the domain label). Names are normalised (corporate suffixes, parentheses and ®/™ removed) and de-duplicated. `partner_type` is `"industry"` when partners exist, else `""`. |

Parsers tolerate CRLF, BOM, missing sections, HTML entities and stray whitespace. Rules are generic: nothing is keyed to individual projects.

## API
| endpoint | |
|---|---|
| `GET /api/projects` | `{"count": N, "projects": [...]}` – filters below |
| `GET /api/projects/<id>` | one project, `404 {"error": …}` when unknown |
| `GET /api/facets` | `{field: [{"value", "count"}, …]}` for `difficulty, technology_trend, product, platform, project_type, application_area, hardware_required, partner, has_partner` (count = number of projects; sorted by count desc). Accepts the same filters; counts are then *disjunctive*: each field ignores its own filter, so ticking a box does not zero its siblings. |
| `GET /` | Project Explorer UI |

Filters: `q` (case-insensitive; every whitespace-separated word must occur in title, summary, expertise items or product names), `difficulty`, `technology_trend`, `product`, `platform`, `project_type`, `application_area`, `hardware_required`, `partner` (case-insensitive exact value match), `has_partner=true|false` (anything else → `400`). Repeating a parameter ORs its values; different parameters are ANDed. Unknown parameters are ignored. Errors are JSON (`404`, `405`, `400`).

## Explorer UI
One self-contained HTML page (`catalog_explorer/static/index.html`, no external resources): search box, facet checkboxes with counts,
removable filter chips, result count and one card per project (`data-project-id="<id>"`, title linking to `project_url`, summary,
difficulty badge, trend and product tags). State lives in the URL query string using the API parameter names
(e.g. `/?difficulty=Advanced&platform=Simulink&q=drone`), so views are shareable and survive reload / back / forward. All catalog text is inserted with `textContent` (no `innerHTML`).

## Layout
```
catalog                   executable entry point
catalog_explorer/parser.py   page parsing (sections, header table, megatrend links)
catalog_explorer/rules.py    dictionaries + classification rules
catalog_explorer/catalog.py  build/write the catalog
catalog_explorer/server.py   filter engine, facets, HTTP handler
catalog_explorer/static/index.html
tests/                    parsers (real + synthetic pages), rules, catalog invariants, API over HTTP, UI (static + executed under node when available), CLI
```

## Limitations
Classification is keyword-based and therefore approximate (e.g. a project that merely mentions "market" in prose may not be tagged Finance). Tune the tables in `rules.py`; tests assert rule behaviour and catalog invariants, not per-project labels.
