# Lua 5.5 interpreter

A from-scratch interpreter for the Lua 5.5 language and its standard libraries, written in C11 with no third-party
code (libc and libm only). The Lua 5.5 reference manual in `docs/manual.of` is the specification: besides the
Lua 5.4 feature set it implements the 5.5 `global` declarations (`global x`, `global<const> *`, `global function`),
read-only loop control variables, and the 4-value generic `for` with a closing value.

## Requirements

Linux x86-64 with `gcc` and `make` (the coroutine context switch is x86-64 assembly). Nothing else to install.

## Build, run, test

    make                         # builds bin/luai (gcc -O2)
    ./lua script.lua a b         # run a script; `arg` and `...` hold "a", "b"
    ./lua -                      # run a program read from stdin (also: ./lua < prog.lua)
    ./lua -e 'print(1 + 1)'      # run a command-line chunk
    make test                    # build, then run the whole test-suite (same as: sh tests/run.sh)

`./lua` is a small launcher script: it builds `bin/luai` on first use (so a fresh checkout works with just `./lua`)
and then `exec`s it. Uncaught errors print `lua: <message>` followed by a `stack traceback:` to stderr and exit with
status 1; `os.exit(n | true | false)` sets the status; syntax errors report `file:line: message near 'token'`.

## Test-suite (`tests/`)

`tests/run.sh` builds the interpreter, then runs and reports (PASS/FAIL per file, non-zero exit on any failure):

| Directory | What it contains |
| --- | --- |
| `tests/cases/*.lua` | self-checking Lua scripts (`assert`): lexer, operators and number semantics, statements/closures/goto/varargs/tail calls, errors and messages, metatables, 5.5 declarations and `<close>`, coroutines, GC, strings (patterns, `format`, `pack`), tables, math/utf8, os/io, base/package/debug, manual examples, table internals, robustness limits |
| `tests/cli/*.sh` | command-line behaviour: `arg`, exit codes, stderr/traceback format, stdin programs, `os.exit`, stdin reading |
| `tests/bench/*.lua` | timed tests (`-- limit: N` seconds in the header): `fib(25)`, 1e6/1e7-iteration loops, 1e6 table operations, sorting 1e5, 1e7-byte strings, coroutine switching, pathological shapes (190000-deep recursion, 5000-term operator chains, 1e6-character pattern subjects, 200000-term concatenation, ...), and `requirements_perf.lua` which asserts each performance requirement individually |
| `tests/fixtures/` | modules loaded by the `require`/`dofile` tests |

Expected values are derived from the manual's definitions and examples (the manual's own examples are in
`tests/cases/manual_examples.lua` and `strings.lua`), not by recording the interpreter's output.

## Design

* **Front end** (`src/parse.c`): source -> tokens -> AST. Variables are resolved at parse time to frame slots
  (locals), upvalue indices, or `_ENV` field accesses (globals). Locals captured by closures live in heap boxes; all
  other locals live directly in the frame (`alloca`'d on the C stack). The 5.5 rules for `global` declarations and
  `<const>`/`<close>` attributes are enforced at compile time; `goto` visibility and "jumps into the scope of a
  local" are checked per block. Parser nesting is limited to 190 levels (`chunk has too many syntax levels`);
  `a..b..c` chains and long `if/elseif` chains are handled iteratively.
* **Evaluation** (`src/interp.c`): a tree-walking interpreter over the resolved AST. Multiple results travel through
  a per-thread return buffer; `return f(x)` is a proper tail call (trampoline in `call_lua`). Errors use
  `setjmp/longjmp`; `pcall`/`xpcall` catch them (message handlers run at the raise point so tracebacks see the
  failing stack), to-be-closed variables are unwound on every exit path, and runtime errors carry
  `chunk:line:` plus variable information (`local 'x'`, `global 'f'`, `field 'a'`, `upvalue`, `method`, `constant`).
* **Memory** (`src/gc.c`, `src/table.c`): stop-the-world mark & sweep. Heap objects are marked exactly; C stacks
  (main and every coroutine) and registers are scanned conservatively, so interpreter code can keep `Value`s in C
  locals. Collections run only at safe points (function entry, loop back edges), where no call results are in
  flight; frames are zero-initialised and the stack below shallow calls is scrubbed so stale words do not retain
  garbage. Short strings (<= 40 bytes) are interned; long strings hash lazily, so `s = s .. x` loops cost one copy
  per step. Tables have an array part plus an open-addressing hash part; integer keys migrate to the array part
  (append path and density-based rehash), `next` tolerates assigning `nil` during traversal.
* **Coroutines** (`src/lib_coroutine.c`): each coroutine owns a lazily-committed 8 MiB `mmap` stack (1 MiB if that
  fails) and switches with a tiny assembly routine, so `yield` works across `pcall`, metamethods, iterators and
  library callbacks such as `table.sort` comparators. Stacks of dead or collected coroutines go back to a pool.
* **Stacks and limits**: the interpreter runs on a 1 GiB lazily-committed stack with a call-depth limit of 200000;
  every thread checks the stack pointer, so runaway recursion (Lua, metamethod, `pcall`, `gsub` callbacks, ...) and
  huge argument lists raise a catchable `stack overflow` error instead of crashing. Pattern matching is iterative
  per character and nests at most 200 pattern items (`pattern too complex`).
* **Libraries**: `lib_base.c` (base), `lib_string.c` (patterns, `format`, `pack`/`unpack`), `lib_table.c` (introsort
  that honours `__index`/`__newindex`/`__len`), `lib_math.c` (xoshiro256** `random`), `lib_utf8.c`, `lib_os.c`,
  `lib_io.c` (stdio-backed file userdata, `popen`), `lib_package.c` (`require`/`package` and a minimal `debug`).

## Performance (typical, this machine)

`fib(32)` 0.4 s; 5e7-iteration `for` loop 0.8 s; 5e6 method calls 0.5 s; 1e7-element array fill + sum 0.8 s;
sorting 3e5 numbers 0.1 s; 5e5 coroutine switches 0.1 s; sieve to 5e6 1.1 s. The performance requirements
(`fib(25)`, 1e6-iteration loop, 1e6 table operations, ...) are asserted by `tests/bench/requirements_perf.lua`.

## Limitations and assumptions

* `string.dump` and binary chunks are not supported (`load` accepts text chunks only); there is no C API and
  `package` loads no C modules (`package.loadlib` reports "dynamic libraries not enabled").
* `__gc` and `__mode` are accepted and ignored (finalizers never run, weak tables are strong); `io` files are
  closed when collected.
* `debug` is minimal: `traceback`, `getinfo`, `getupvalue`/`setupvalue`, metatable access and the registry;
  `getlocal`/`sethook` are inert.
* Only the "C" locale. Linux x86-64 only (assembly context switch, `ucontext` for the main stack).
* The remaining design decisions and assumptions are recorded in `.orchestrator/requirements.md`.
