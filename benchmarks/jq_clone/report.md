# Benchmark report — jqlang/jq

**Ticket:** [`task.md`](task.md) (DATA-500). It asks for a complete standalone jq: the full language, all
builtins and CLI options, and jq's output formatting. The official jq manual (`manual.yml`) was provided as
the normative input.

**Reference execution:** the hidden harness [`compare.py`](compare.py) parses the repo's own test files
(`jq.test`, `man.test`, `base64.test`, `uri.test`, `onig.test`, `manonig.test`) and runs every case through
jq built from the repo and through the generated `./jq`. It compares output values case by case. Only the
914 cases that the reference itself passes in this harness are counted.

## Result (attempt 1): **817/914 cases (89%)**
The threshold-based score is 0.67.

| test file | passed |
|---|---|
| jq.test | 491/579 |
| man.test (every manual example) | **238/238** |
| manonig.test | 18/18 |
| onig.test (regex) | 44/49 |
| base64.test / uri.test | 8/10, 18/20 |

The failures cluster in:
- the exact text of runtime error messages inside `try … catch .`;
- a few regex edge cases: empty-match iteration, lazy quantifiers with `\b`, optional named groups;
- a program beginning with `-` being parsed as a CLI option.

**Process:** milestone mode with 2 milestones (core language, then builtins/formats/regex/dates). 5 turns on
one session. $4.79.

**Harness fix:** deeply nested JSON outputs (`[[[[…]]]]` tests) exceeded Python's recursion limit during
normalisation; such cases now fall back to a text comparison.
