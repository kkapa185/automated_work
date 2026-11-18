# Benchmark report — commonmark/cmark

**Ticket:** [`task.md`](task.md) (DOCS-77). It asks for a CommonMark → HTML renderer and CLI with cmark-identical
output, `--unsafe/--smart/--hardbreaks/--nobreaks/--sourcepos`, and linear-time behaviour. The CommonMark
spec was provided as the normative input.

**Reference execution:** the hidden harness [`compare.py`](compare.py) runs:
- the repo's own spec runner `test/spec_tests.py` (652 examples), plus `smart_punct.txt` and `regression.txt`;
- the repo's `pathological_tests.py`, which checks correctness and time limits on adversarial inputs;
- 28 real-world READMEs, compared **byte for byte** with cmark built from the repo, plus each option.

## Result (attempt 1): score 0.79 (11/14 checks)
| check | result |
|---|---|
| spec examples | **652/652** |
| smart punctuation | 16/16 |
| regression suite | 34/36 |
| pathological inputs | 21/24 (timeouts on "issue #389" and very deeply nested lists) |
| real-world documents byte-identical | **28/28** |
| `--unsafe`, `--smart`, `--hardbreaks` | identical |
| `--sourcepos` | differs |

**Process:** 4 turns on one session. The planner judged it a single-milestone build. $2.05, 18 min.

**System change triggered:**
- New engineering principle: when a ticket states performance or complexity requirements, write timed
  benchmark tests at the stated sizes on worst-case input shapes (deep nesting, long runs of one token,
  repetitions) and fix any super-linear behaviour. The renderer met the general linear-time requirement,
  but its own tests never probed the deeply nested list shapes that the reference suite uses.
- Test: `tests/test_phases.py::test_prompts_require_worst_case_performance_tests`.
