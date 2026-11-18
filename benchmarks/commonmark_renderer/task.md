# DOCS-77: CommonMark Markdown → HTML renderer (`cmark`-compatible CLI)

Implement a complete CommonMark parser and HTML renderer as a command-line tool `./cmark` (any
language; do not wrap an existing Markdown library such as cmark, commonmark.js, markdown-it, mistune,
marko, python-markdown or pulldown-cmark). The CommonMark specification is provided in `docs/spec.txt`
and is **normative**: every rule, and every example in it, must hold.

* `./cmark [FILE...]` reads Markdown from the files (concatenated) or stdin and writes HTML to stdout,
  rendered exactly like the reference implementation `cmark` (block structure, inline parsing with the
  delimiter-run algorithm, link reference definitions, entity/numeric character references, HTML
  blocks and raw HTML, tabs as specified, lazy continuation, list tightness, autolinks, hard/soft
  breaks, backslash escapes, code spans, fenced/indented code, setext/ATX headings, thematic breaks,
  block quotes). HTML output format identical to cmark's (e.g. `<p>`, `<pre><code class="language-x">`,
  attribute escaping, `\n` placement).
* Options: `--unsafe` (raw HTML and dangerous URLs are passed through; without it raw HTML is replaced
  by `<!-- raw HTML omitted -->` and `javascript:`/`vbscript:`/`file:`/non-image `data:` URLs are
  emptied), `--hardbreaks`, `--nobreaks`, `--smart` (smart quotes, dashes, ellipses), `--sourcepos`,
  `--to html` (default).
* Robustness: linear-time behaviour on adversarial inputs (deeply nested brackets/emphasis/block quotes,
  many link reference definitions, long runs of backticks, etc.) — every input of a few hundred kB must
  render in well under a few seconds.

Deliverables: the renderer, a test-suite that runs every spec example, adversarial-input performance
tests, and a README.
