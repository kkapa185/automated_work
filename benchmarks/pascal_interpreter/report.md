# Benchmark report — rspivak/lsbasi (Let's Build A Simple Interpreter, part 19)

**Ticket:** [`task.md`](task.md) (LANG-19). It covers a Pascal-subset tree-walking interpreter with
semantic analysis, exact error messages and a `--stack` activation-record trace.

**Reference execution:** the hidden harness [`compare.py`](compare.py) runs the reference
`part19/spi.py` and the generated `./spi` on the same corpus: 8 programs of my own plus every `.pas` file
in parts 14–19 of the repo, with and without `--stack`. It compares stdout byte for byte, plus the exit
status. Programs on which the *reference itself* crashes with a Python traceback are excluded as
undefined behaviour.

## Score history
| attempt | system | score | cause of the gap |
|---|---|---|---|
| 1 | `86683d9` | 0.74 | **Ticket error:** I said one blank line follows each stack dump; the reference prints two (`str` ends in `\n\n` and `print` adds `\n`). The system followed the ticket exactly. The harness also counted a reference crash case. |
| 2 | `c8787c2` | 0.85 | **Ticket ambiguity:** the reference grammar allows only one `VAR` keyword per block, so a second one is a `ParserError`. The generated interpreter accepted several, as real Pascal does. |
| 3 | `7c307c4` | **1.00** | – |

**Process (attempt 3):** 3 turns on one session: plan → implement → review (PASS). $0.53 (corrected).

**What changed:**
- Tickets: the exact blank-line bytes, and the single-`VAR` rule.
- Harness: skips programs on which the reference crashes.
- No system defect: in every attempt the system did what the ticket said. The lesson is about ticket
  precision. I now verify every format claim in a ticket against the reference's literal output.
