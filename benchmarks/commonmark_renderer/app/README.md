# cmark (Python) — a CommonMark 0.31.2 → HTML renderer

A from-scratch implementation of the CommonMark specification (`docs/spec.txt`, version 0.31.2)
with a `cmark`-compatible command line. Pure Python 3 standard library; no Markdown library is used.

## Install / run

No installation or dependencies (Python 3.9+).

```
./cmark [OPTIONS] [FILE...]      # files are concatenated; stdin when no file is given
echo '*hi*' | ./cmark            # -> <p><em>hi</em></p>
```

Options: `--to html` (default and only format), `--unsafe`, `--hardbreaks`, `--nobreaks`,
`--smart`, `--sourcepos`, `--version`, `--help`. Errors (unreadable file, unknown option or
format) go to stderr with exit status 1.

* Default (safe) mode replaces raw HTML by `<!-- raw HTML omitted -->` and empties
  `javascript:`, `vbscript:`, `file:` and non-image `data:` URLs (`data:image/png|gif|jpeg|webp` is kept).
  `--unsafe` passes everything through.
* `--hardbreaks` renders soft breaks as `<br />`, `--nobreaks` as a space (hardbreaks wins if both).
* `--smart` gives curly quotes, `--`/`---` → en/em dashes (cmark's 2/3-multiples rule), `...` → `…`.
* `--sourcepos` adds `data-sourcepos="line:col-line:col"` to block elements.

As a library: `from cmarklib import markdown_to_html; markdown_to_html(text, unsafe=False, ...)`.

## Tests

```
make test              # or: python3 tests/run_all.py
python3 -m unittest tests.test_spec     # all 652 spec examples
python3 -m unittest tests.test_perf     # adversarial inputs, time-limited (CMARK_PERF_LIMIT secs, default 5)
```

* `tests/test_spec.py` extracts every example from `docs/spec.txt` at run time and compares the exact
  HTML (run with `--unsafe` semantics, as the examples contain raw HTML, like cmark's own spec runner).
* `tests/test_options.py` – CLI, safe/unsafe, breaks, smart, sourcepos, URL/attribute escaping.
* `tests/test_perf.py` – ~50 adversarial generators (deep brackets/emphasis/quotes/lists, many reference
  definitions, backtick runs, unterminated HTML constructs, …) each of 100–500 kB.

## Design

```
bytes ─► prepare_text (UTF-8, BOM, NUL, CR/CRLF) ─► BlockParser ─► AST ─► InlineParser (per leaf) ─► render_html
```

* `cmarklib/blocks.py` – line-by-line block parser following the spec's container/leaf strategy:
  open-container stack, continuation checks, block starts in priority order, lazy continuation,
  tab handling by columns (partially consumed tabs), list tightness, link reference definitions
  (extracted when a paragraph is closed, using index scanning rather than slicing).
* `cmarklib/inlines.py` – inline parser: delimiter-run algorithm with `openers_bottom`
  (rule of 3, smart quotes), bracket stack with amortised "links may not contain links"
  deactivation, code spans via per-length sorted position index + bisect, entity table from
  `html.entities.html5`, autolinks, raw HTML with memoised failed scans.
* `cmarklib/render.py` – iterative (non-recursive) renderer producing cmark-style output.
* Linear time: every potentially repeated scan is either bounded (labels ≤ 999 chars, paren nesting ≤ 32),
  memoised (unterminated `-->`, `?>`, `]]>`, `>`), or amortised; no recursion anywhere, so
  100k-deep nesting neither overflows the stack nor goes quadratic.

## Assumptions

* Only `html` output is supported by `--to`; other formats are rejected.
* Smart punctuation and `--sourcepos` positions follow cmark's documented conventions (they are not
  part of the spec); source columns count characters, not bytes.
* Reference labels are matched with Unicode case folding (`str.casefold`).
