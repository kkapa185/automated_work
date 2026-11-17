# HUB-77 Requirements: Challenge Project catalog + Project Explorer

## Product
A Python 3 (stdlib-only runtime, pytest for tests) CLI/web-service. `./catalog build <hub> -o out/projects.json`
parses the MATLAB & Simulink Challenge Project Hub snapshot in `hub/` into a structured JSON catalog (one record per
challenge project) using deterministic keyword/section rules. `./catalog serve <hub> --port N` builds the catalog in
memory and serves a JSON API (`/api/projects`, `/api/projects/<id>`, `/api/facets`) plus a single-page Project
Explorer UI (`/`) with search, facet checkboxes with counts, filter chips, result count and project cards, with
filter state in the URL query string. Code lives in package `catalog_explorer/`; README documents extraction rules.

## Acceptance criteria
### Parsing / catalog
- R1  Only folders `projects/<X>/` that contain `README.md` are projects (83 in the snapshot); folders without one (e.g. the
      submissions-only "Traffic Data Analysis for Modeling…" folder), `ALL_SUBMISSIONS.md`, `submissions.md`, `Classroom Challenge Projects/` are ignored. Output sorted by numeric id then title.
- R2  `id` = value under `## Project Number` (string, digits; trimmed). Fallback: `tfa_2=` param of the signup form link. Missing => project skipped with a warning on stderr (never crash).
- R3  `title` = `<h1>` in the header table (tags/whitespace stripped, HTML entities unescaped); fallback first Markdown `# ` heading, then folder name.
- R4  `project_url` = `https://github.com/mathworks/MATLAB-Simulink-Challenge-Project-Hub/tree/main/projects/<urllib quote of folder name>`; `source_file` = `projects/<folder>/README.md` (relative to hub, posix slashes).
- R5  `summary` = first `<p>` after the `<h1>` in header table (tags stripped, whitespace collapsed); one sentence: if longer than one sentence, first sentence only. Fallback: first sentence of `## Project Description`.
- R6  `thumbnail` = first `<img src>` in the header table (the project image); empty string if none.
- R7  `technology_trends`: megatrend page names (file stem of `megatrends/*.md`) whose project links (`projects/<folder>` hrefs, URL-decoded; matched by folder name, with a normalised title-match fallback so "Modeling"/"Modelling" variants resolve) include the project. Sorted. Empty megatrend pages (Neuroscience) yield no entries. Unlisted projects get `[]`.
- R8  `expertise_gained_original`: items of `## Expertise Gained` split on commas/semicolons/newlines/bullets, trimmed, whitespace-collapsed, case-insensitive de-duplicated preserving first spelling and order.
- R9  `academic_levels`: parsed from `## Project Difficulty`; recognises Bachelor / Master's (curly or straight apostrophe, "Master’s level") / Doctoral; canonical spelling `Bachelor`, `Master's`, `Doctoral`, ordered Bachelor<Master's<Doctoral, de-duplicated. Missing => `[]`.
- R10 `difficulty` in {Beginner, Intermediate, Advanced}: base from academic levels (only Bachelor => Beginner; Bachelor+Master's, Master's, or all three => Intermediate; Master's+Doctoral, Doctoral => Advanced; none => Intermediate), then a scope adjustment of at most ±1 step using documented signals (explicit words "beginner/introductory/entry-level" down; "advanced/research-level/state-of-the-art/PhD" in the Difficulty section up; many "Advanced project work" items plus required hardware up). Documented in README, pure function, unit-tested.
- R11 `mathworks_products`: canonical names from a documented product dictionary (alias regex -> canonical name, e.g. "Deep Learning Toolbox", "Robotics System Toolbox", "Simulink Coder", "Stateflow", "Simscape Electrical", "MATLAB Coder", "Mapping Toolbox"...), found in (a) `## Suggested MathWorks Products` if present, (b) links to mathworks.com/products/* or mathworks.com/help/<docroot>/ in the page (docroot -> product), (c) textual mentions of product names. Sorted unique. "MATLAB" and "Simulink" themselves are platforms, not products (excluded from products).
- R12 `mathworks_platforms` subset of ["MATLAB","Simulink"], in that order: Simulink if page mentions Simulink or any Simulink-family product (Simscape, Stateflow, Simulink Coder...), MATLAB if page mentions MATLAB or uses MATLAB-only toolboxes or no Simulink-only signal; at least one is always present (default MATLAB).
- R13 `project_type` ⊆ the 11 allowed values, `application_areas` ⊆ the 10 allowed values: deterministic weighted keyword rules over title, summary, expertise, impact, description, products and megatrends (rule tables in code, documented in README). Each project gets ≥1 project_type and ≥1 application area (fallbacks: "System Design"/"Modeling & Simulation"; "Education / Research"). Output order follows the canonical list order.
- R14 `hardware_required` in {None, Optional, Required}: `## Required Hardware` section with content, or phrases like "must be implemented on", "requires … board" => Required; hardware mentions in "optional"/"if available"/"deploy on"/"hardware-in-the-loop" contexts or hardware tags found => Optional; else None. `hardware_tags`: hardware names from a documented dictionary (Raspberry Pi, Arduino, STM32/Nucleo, Jetson, BeagleBone, Cortex-M, Pixhawk, Parrot Minidrone, Tello, TurtleBot, Universal Robots UR3/UR5, LiDAR, IMU, GPS, camera, RTL-SDR/ADALM-PLUTO SDR, FPGA, ...), canonical, sorted unique. Hardware tags non-empty with "None" classification is not allowed (at least Optional).
- R15 Partners: `partners` = names from "developed in collaboration with **X**" sentences and the `Industry Partner` block (name inferred from logo link domain/alt via a documented domain->name table, else the domain label); normalised (strip "Inc.", punctuation, dedupe); `has_partner` = bool(partners) — also true if an Industry Partner block exists with a link only; `partner_type` = "industry" if has_partner else "".
- R16 Robustness: parsers tolerate CRLF, missing sections, extra whitespace, HTML entities (`&#58;`), BOM; unreadable/odd files raise no unhandled exceptions. Build is deterministic (byte-identical output across runs) and writes UTF-8 JSON (indent 2, `ensure_ascii=False`), creating parent dirs of `-o`.
- R17 CLI: `./catalog build <hub> -o <file>` (exit 0, prints count to stderr/stdout), missing hub dir => exit 2 with message; `./catalog serve <hub> --port N [--host H]` (default host 127.0.0.1); `-h` works. `./catalog` runs from any cwd, no third-party deps.

### API
- R20 `GET /api/projects` => `{"count":N,"projects":[...]}`, same record schema as the JSON file, ordered like the catalog.
- R21 Filters (AND across different params; OR across repeated values or comma-free repeats of the same param): `q` (case-insensitive substring; multi-word q requires every word, over title, summary, expertise items, products), `difficulty`, `technology_trend`, `product`, `platform`, `project_type`, `application_area`, `hardware_required`, `partner`, `has_partner=true|false`. List-valued fields match if any listed value matches (case-insensitive exact on value). Invalid `has_partner`/unknown `difficulty`-type values => results are simply filtered (empty), invalid `has_partner` value => 400 JSON error. Unknown query params ignored.
- R22 `GET /api/projects/<id>` => project object; unknown id => 404 `{"error": "..."}` JSON. Unknown route => 404 JSON; non-GET => 405 JSON.
- R23 `GET /api/facets` => object keyed by filterable field (`difficulty, technology_trend, product, platform, project_type, application_area, hardware_required, partner, has_partner`) -> list of `{"value":..., "count":...}` sorted by count desc then value; counts are numbers of projects (not occurrences). `has_partner` values "true"/"false". Also accepts the same filters; counts are then disjunctive (each field is counted over projects matching all filters except that field's own).
- R24 `GET /` returns an HTML page (single file, inline JS/CSS, no external resources). UI: search box, facet checkbox groups with counts, active filter chips (click to remove), result count, one card per project with `data-project-id="<id>"`, title link to `project_url`, summary, difficulty badge, trend and product tags. State is read from/written to `location.search` using the same parameter names as the API (shareable, reload-restorable, back/forward works). UI renders safely (text via textContent / escaping, no XSS from catalog data); responsive.
- R25 Responses have correct Content-Type and UTF-8; server runs on `--port 0` for tests, handles concurrent requests (ThreadingHTTPServer), CORS not required.

### Deliverables
- R30 Tests (pytest) from clean checkout: `python -m pytest`; parsers on real hub pages and synthetic pages (malformed/missing sections), classification rules, catalog invariants over all real projects (83 projects, unique ids, enum validity, URL shape), API filters/facets via real HTTP on an ephemeral port, UI smoke test (HTML contains the required elements and the JS parses/ runs under node if available, else static checks), CLI build/serve tests.
- R31 README: purpose, install (none beyond Python ≥3.10; `requirements-dev.txt` pins pytest), run, test, full extraction rules and rule tables, API reference, design notes, known limitations.

## Assumptions
- A1 The sample in `hub/` is authoritative; 83 READMEs exist, all follow the same section template (Project Number / Difficulty / Expertise Gained …); the duplicate title spelling variants (Modeling/Modelling) are separate folders, only the one with README counts.
- A2 `id` unique; if duplicates occur the later one is kept in output with warning (none expected).
- A3 `mathworks_products` allows the product names from the page's "Suggested MathWorks Products" and links; products are deliberately broad (union of all evidence).
- A4 "difficulty" from academic level is the primary signal as the spec says "stated difficulty / academic level and scope".
- A5 Query matching on `product`, `partner`, etc. is case-insensitive exact on whole value; `q` is substring.
- A6 Python stdlib only, so no web-framework dependency risk; pytest is the sole dev dependency.

## Test strategy
unit tests (parsers: R2–R9, R16; classifiers: R10–R15) with synthetic pages; real-data invariants (R1,R7,R30); API tests over HTTP (R20–R23, R25); UI smoke (R24); CLI subprocess tests (R17).
