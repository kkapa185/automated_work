# DOCS-77 requirements

## Product
A CommonMark 0.31.2 parser + HTML renderer delivered as the CLI `./cmark` (Python 3, stdlib only, no
Markdown library). It follows `docs/spec.txt` (normative) and cmark's HTML output conventions, with options
`--unsafe`, `--hardbreaks`, `--nobreaks`, `--smart`, `--sourcepos`, `--to html`, and linear-time behaviour on
adversarial inputs. Ships with a test-suite (all spec examples, extracted from docs/spec.txt at test time),
adversarial performance tests, and a README.

## Acceptance criteria
- R1 `./cmark [FILE...]` reads files (concatenated) or stdin, writes HTML to stdout; unreadable file -> error on stderr, exit 1. `--to html` accepted (default); other formats rejected with exit 1.
- R2 Every example in docs/spec.txt renders to the expected HTML (exact string match, cmark-style output; run with `--unsafe` since the examples contain raw HTML, as cmark's own spec runner does).
- R3 Block structure: paragraphs, ATX/setext headings, thematic breaks, indented/fenced code (info string -> `class="language-x"`), block quotes, lists (ordered start attr, tight/loose), HTML blocks (7 kinds), link reference definitions, lazy continuation, tabs, container/leaf interaction.
- R4 Inlines: backslash escapes, entity/numeric refs (HTML5 table; invalid/0 -> U+FFFD), code spans, emphasis/strong via delimiter-run algorithm (rule of 3), links/images (inline, full/collapsed/shortcut refs, nesting rules), autolinks, raw HTML, hard/soft breaks.
- R5 Output formatting like cmark: HTML escaping of `& < > "` in text, attribute escaping, URL percent-encoding of unsafe chars in href/src (keeping existing %XX and `&` as `&amp;`), `\n` placement, `<hr />`, `<br />`, `<img src alt />` with alt as plain text, title attribute.
- R6 Default (safe) mode: raw HTML inline/blocks replaced by `<!-- raw HTML omitted -->`; links/images with `javascript:`, `vbscript:`, `file:`, and `data:` (except image/png|gif|jpeg|webp) have empty href/src. `--unsafe` passes through.
- R7 `--hardbreaks` renders softbreaks as `<br />\n`; `--nobreaks` renders them as a space; `--smart` converts quotes, `--`/`---` (en/em dashes per cmark algorithm), `...` to ellipsis.
- R8 `--sourcepos` adds `data-sourcepos="l:c-l:c"` to block elements (cmark format).
- R9 Linear-ish time: inputs of a few hundred kB of adversarial content (nested brackets/emphasis/block quotes/lists, many ref defs, backtick runs, `<`/`[`/`!` runs, long lines) render in well under a few seconds; deep nesting must not crash (no recursion overflow).
- R10 Input handling: NUL -> U+FFFD, `\r\n`/`\r` normalised, invalid UTF-8 replaced with U+FFFD, missing final newline OK, empty input -> empty output.
- R11 Deliverables: `cmark`, tests (`tests/`), perf tests, README, Makefile `make test`.

## Assumptions
- Python 3 stdlib only; HTML5 entity names via `html.entities.html5`; Unicode punctuation/whitespace via `unicodedata`.
- cmark output for unsafe-mode raw HTML is verbatim; `--smart` follows cmark's smart punctuation (not in spec.txt).
- Spec examples run with default options; cmark's sourcepos/smart behaviours are tested by hand-derived cases.
- Case folding for reference labels uses Python `str.casefold()` (spec: Unicode case fold).
- Deep nesting limit: cmark-like robust handling by iterative algorithms where practical; recursion limit raised.

## Test strategy
- tests/test_spec.py: parses spec.txt examples (`example` fences, `→` tab marker) -> R2-R6 (and most of R3-R5, R10).
- tests/test_options.py: CLI-level tests for R1, R6-R8 with hand-derived expected output.
- tests/test_perf.py: adversarial generators with time limits -> R9.

## Plan
Files: `cmark` (CLI entry), `cmarklib/{blocks,inlines,render,entities,util}.py`, tests, README, Makefile.
Data flow: bytes -> normalised lines -> block parser (open-container stack, line-by-line, ref defs extracted at paragraph close) -> AST -> inline parser per leaf (delimiter stack, bracket stack) -> iterative HTML renderer.
Risks: quadratic paths (delimiter scans, bracket opener scans, backtick matching, ref-def paragraph re-parse, deep nesting) -> use memoised backtick positions, openers_bottom, bracket-active flags, iterative walkers.
