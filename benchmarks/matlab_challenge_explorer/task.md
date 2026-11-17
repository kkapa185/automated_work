# HUB-77: Challenge Project catalog + Project Explorer for the MATLAB & Simulink Challenge Project Hub

## Context
`hub/` in the workspace is a snapshot of the MATLAB and Simulink Challenge Project Hub content
repository: a top-level `README.md` (program overview and a table of all projects), `megatrends/*.md`
(one page per technology trend listing the projects that belong to it), `projects/<Project Title>/README.md`
(one folder per challenge project, plus `submissions.md` files and `projects/ALL_SUBMISSIONS.md`), and
`Classroom Challenge Projects/`. Students currently browse long Markdown/HTML pages. We need a structured,
searchable catalog generated from that content, and an interactive explorer on top of it.

## 1. Catalog builder
`./catalog build hub -o out/projects.json` parses the hub and writes a JSON array with one object per
challenge project (only real challenge projects: folders under `projects/` that contain a project
`README.md`). Fields:
| field | meaning |
|---|---|
| `id` | the project's number (string), from the project page |
| `title` | project title |
| `project_url` | URL of the project page on GitHub (`https://github.com/mathworks/MATLAB-Simulink-Challenge-Project-Hub/tree/main/projects/<url-encoded folder>`) |
| `source_file` | path of the README relative to `hub/` |
| `summary` | one-sentence description of the project |
| `technology_trends` | the technology trends (megatrend page names, e.g. "Robotics") the project is listed under |
| `mathworks_platforms` | subset of `["MATLAB", "Simulink"]` the project relies on |
| `mathworks_products` | canonical MathWorks product names (toolboxes, blocksets, coders, Stateflow, ...) the project uses or links to |
| `expertise_gained_original` | the "Expertise Gained" items of the project page, normalised (trimmed, de-duplicated) |
| `difficulty` | one of `Beginner`, `Intermediate`, `Advanced`, judged from the project's stated difficulty / academic level and scope |
| `academic_levels` | the academic levels stated on the page (e.g. `["Bachelor", "Master's"]`) |
| `project_type` | list from: Modeling & Simulation, AI / Machine Learning, Control Design, Signal Processing, Optimization, Data Analysis, Embedded / Real-Time, Hardware Integration, System Design, App / UI Development, Verification / Testing |
| `application_areas` | list from: Energy / Sustainability, Automotive, Aerospace, Robotics / Automation, Manufacturing / Industry 4.0, Communications / Wireless, Smart Infrastructure / IoT, Healthcare / Medical, Education / Research, Finance / Economics |
| `hardware_required` | `None`, `Optional` or `Required` |
| `hardware_tags` | hardware named by the project (boards, robots, sensors, ...) |
| `has_partner`, `partners`, `partner_type` | industry partner(s) collaborating on the project (`partner_type` "industry" or "") |
| `thumbnail` | the project's image URL |

Classification fields must be derived from the project text with documented, deterministic rules
(keyword/section analysis), not typed in by hand per project.

## 2. Explorer service
`./catalog serve hub --port <port>` builds the catalog in memory and serves:
* `GET /api/projects` — all projects; query filters (combinable, AND across fields, OR within a
  repeated field): `q` (case-insensitive full-text over title, summary, expertise, products),
  `difficulty`, `technology_trend`, `product`, `platform`, `project_type`, `application_area`,
  `hardware_required`, `partner`, `has_partner=true|false`. Response: `{"count": N, "projects": [...]}`.
* `GET /api/projects/<id>` — one project (404 JSON error if unknown).
* `GET /api/facets` — for every filterable field, each value with its project count.
* `GET /` — a single-page Project Explorer UI: search box, facet filter checkboxes with counts, active
  filter chips, a result count, and one card per project (title linking to `project_url`, summary,
  difficulty badge, trends and products as tags). Filter state is kept in the URL query string so views
  can be shared. Each card element carries `data-project-id="<id>"`.

## Deliverables
Code, automated tests (parsers on real and synthetic pages, classification rules, API filters and
facets, UI smoke test), and a README documenting the extraction rules.
