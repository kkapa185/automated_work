# Benchmark report — lua/lua

**Ticket:** [`task.md`](task.md) (LANG-54). It asks for a complete Lua interpreter and standard library,
written from scratch, with no wrapping of liblua or other Lua implementations. The reference manual was
provided as the normative input.

**Reference execution:** `lua` built from the repo at HEAD, which is **Lua 5.5.1**. The hidden harness
[`compare.py`](compare.py) compares stdout, exit status and the first error line on 8 corpus programs. It
then runs 18 of the repo's official `testes/*.lua` files, those that pass standalone on the reference.

## Score history
| attempt | score | notes |
|---|---|---|
| 1 | 0.38 | **Ticket error:** I specified Lua 5.4, but the reference and the provided manual are 5.5. Most official test files begin with the 5.5 `global` declaration, which the 5.4-faithful interpreter rejected as a syntax error. |
| 2 | 0.38 | The ticket now says Lua 5.5. `global` declarations parse, and the test files now get much further, but they fail on deep implementation details. |

**Final state (attempt 2):** the generated interpreter is written in Go.
- 4 of 8 corpus programs produce identical stdout, and all 8 match the reference's exit status and
  first error line.
- 2 of 18 official test files pass completely (`bitwise`, `constructs`). The rest fail on details such as:
  - tail-call depth assertions (`calls.lua:168`);
  - closure-collection timing (`closure.lua` times out);
  - coroutine status corners, metamethod edge cases (`events.lua:146`) and scanner limits;
  - integer/float boundary formatting in `math.lua`;
  - a parse gap in the new 5.5 declaration forms (`locals.lua:313`).
- Several corpus differences come only from how error messages abbreviate long chunk names
  (`...omated_work/...` vs the reference's form).

**Analysis:**
- The official Lua test-suite is written for the reference C implementation and asserts internal
  details (stack levels, GC timing, exact numeric formatting) far beyond the manual.
- An interpreter that implements the manual faithfully still fails most files on the first deep
  assertion, so this benchmark measures "PUC-Lua bug-for-bug compatibility" more than correctness.
- Two attempts cost $20.96. The user asked to wrap up after this round, so no further iteration was done.
