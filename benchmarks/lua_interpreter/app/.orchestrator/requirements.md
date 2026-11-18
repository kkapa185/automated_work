# Requirements: Lua 5.4 interpreter (LANG-54)

## Product
A from-scratch Lua 5.4 interpreter and standard library written in Go (no existing Lua implementation used),
run as `./lua [script [args]]` from the workspace root. `./lua` is a POSIX shell launcher that builds the Go
binary (`go build`, into `bin/`) when missing/stale and then execs it. Design: lexer -> parser (AST) ->
resolver (local slots/upvalues) -> tree-walking evaluator with compiled closures; coroutines run on goroutines
with channel hand-off; strings are byte strings; tables have array + hash parts. Manual `docs/manual.of` is normative.

## Acceptance criteria
R1  CLI: `./lua script.lua a b` runs script, sets global `arg` (arg[0]=script, arg[1..]=args, `...` = args); no script reads stdin; `-e`-less minimal CLI is sufficient.
R2  Uncaught error: stderr gets `lua: <msg>` plus `stack traceback:` text, exit status 1. Syntax errors likewise (`lua: file:line: msg near 'tok'`). Normal exit 0; `os.exit(n|true|false)` honoured.
R3  Types: nil, boolean, integer (64-bit wrapping) and float subtypes, string (bytes), table, function, thread, userdata (file handles). `type`, `math.type`.
R4  Number formatting: floats `%.14g`, with `.0` appended when it looks like an integer; `inf`, `-inf`, `nan`/`-nan`; integers decimal. String<->number coercions per §3.4.3; `1e15`, `2^53`, `10//3`, `7//0.0`, `-7//2 = -4`, `-7%3 = 2`, `5.5%-2`, int division/modulo by zero error ("attempt to perform 'n//0'", "attempt to perform 'n%%0'").
R5  Lexer: comments `--`, `--[==[ ]==]`, long strings (leading newline skipped), escapes `\n \t \\ \" \' \a \b \f \r \v \ddd \xXX \z \u{XXX}` and line continuation, decimal/hex ints (wrap), hex floats `0x1p4`, `0x.8`, floats `3.`, `.5e2`; integer literal overflow becomes float.
R6  Operators and precedence per §3.4.8 (or < and < comparison < | < ~ < & < shift < .. (right) < +- < */ // % < unary < ^ (right)); bitwise ops on ints (floats with exact int value coerced, else error "number has no integer representation"); comparisons int/float exact; string comparison; `..` of numbers; `#`.
R7  Statements: local/global assign, multiple assignment (evaluate all RHS first), multiple returns/adjustment, varargs (`...`, `select('#')`, `table.pack`), `if/while/repeat` (until sees body locals)/numeric for (int and float, overflow-safe, step 0 error)/generic for (4 values incl. closing value), `break`, `goto`/labels (continue idiom, nested loops), `do` blocks, method defs `function a.b:c()`.
R8  Local attributes `<const>` (compile error "attempt to assign to const variable 'x'") and `<close>` (calls `__close(value, err)` on scope exit, normal/break/return/error/goto, reverse order; non-closable value error).
R9  Closures with correct per-iteration upvalue capture; proper tail calls (depth 1e6 tail recursion must not overflow); deep non-tail recursion ~200000 levels works or raises catchable "stack overflow" error (never crashes the process).
R10 Metatables/metamethods: `__index __newindex` (function or table chains), `__call`, `__eq __lt __le`, `__concat __len __unm __bnot`, all arithmetic and bitwise (`__add __sub __mul __div __mod __pow __idiv __band __bor __bxor __shl __shr`), `__close`, `__tostring`, `__name`, `__pairs`, `__metatable` (getmetatable/setmetatable protection), `__gc`/`__mode` accepted and ignored.
R11 Errors: runtime messages with `chunkname:line:` prefix, e.g. `attempt to perform arithmetic on a nil value (global 'x')`, `attempt to index a nil value (field 'y')`, `attempt to call a nil value (global 'f')`, `attempt to compare number with nil`, `attempt to concatenate a table value (local 't')`; variable info for local/global/field/upvalue/method/constant. `error(v, level)` position prefix for string messages (levels 0,1,2), non-string error values preserved; `pcall`, `xpcall` with handler (receives original value, traceback via `debug.traceback` available), `assert` (message / default "assertion failed!"), error objects through coroutines; chunk names like `script.lua` and `[string "..."]`.
R12 Base lib: print, type, tostring, tonumber (bases 2-36, whitespace, hex, floats, invalid->nil/fail), pairs/ipairs/next (modifying existing fields during traversal ok), select (negative), rawget/rawset/rawequal/rawlen, setmetatable/getmetatable, assert, error, pcall, xpcall, load (string or function reader, chunkname, mode, env param; returns nil,msg on syntax error), loadstring absent, dofile, loadfile, require (package.path `./?.lua;./?/init.lua`, package.loaded, package.preload, package.searchers basic), collectgarbage (`count` returns a number, others return 0), `_G`, `_VERSION == "Lua 5.4"`, `_ENV` semantics (local _ENV, function param _ENV, load env).
R13 string: len sub upper lower rep(with sep) reverse byte char format (`%d %i %u %c %x %X %o %e %E %f %F %g %G %a %A %s %q %%` with flags/width/precision; `%d` with float-integral ok, else error "number has no integer representation"; `%s` uses __tostring) find match gmatch(with init) gsub (string/table/function repl, `%0-%9`, anchors, `%b()`, `%f[set]`, back-references, classes `%a %d %l %s %u %w %x %p %c %g`, sets, `-*+?`, position captures `()`, max n) pack/unpack/packsize (formats `< > = ! b B h H i[n] I[n] l L j J T f d n s[n] z x X ' '`), string indexing via metatable (`("x"):upper()`, `#s`), string arithmetic coercion ("10"+1 = 11).
R14 table: insert (position checks), remove, concat (numbers, error on invalid value), sort (comparator, "invalid order function" detection not required, stable enough for correctness, errors propagate), unpack(i,j), pack (n), move; respect __index/__newindex/__len metamethods.
R15 math: abs ceil floor sqrt sin cos tan asin acos atan(y,x) exp log(x,base) pow-less, fmod (int and float, zero error), modf, huge, pi, maxinteger, mininteger, tointeger, type, ult, max, min, random (0 args float; m; m,n; errors on empty interval)/randomseed (deterministic for same seed).
R16 utf8: char, charpattern, codepoint, len (returns nil,pos for invalid), offset, codes (with lax flag).
R17 coroutine: create resume yield status wrap isyieldable running close; yield across pcall, in iterators, passing values both ways, error in coroutine returns false,msg, "cannot resume dead coroutine", wrap propagates errors, status values suspended/running/normal/dead, closing coroutine runs pending `<close>`.
R18 os/io: os.time (table arg normalising, default now), clock, date (formats `%Y-%m-%d %H:%M:%S` etc., `*t`, `!` UTC), getenv, exit, remove, rename, tmpname, difftime; io.write (returns file), io.read formats (`l L n a` and counts, also with leading `*`), io.lines (stdin or filename), io.open modes r/w/a/+ b, file:read/write/lines/seek/close/flush/setvbuf, io.stdout/io.stderr/io.stdin, io.close, io.output/io.input, io.type, tostring(file) "file (0x...)".
R19 debug (minimal): debug.traceback(msg), debug.getinfo (currentline, short_src, source, what best-effort), debug.sethook no-op, getmetatable/setmetatable.
R20 Performance: `fib(25)` recursive < 2s, 1e6-iteration arithmetic loop < 1s, string/table heavy loops reasonable (table insert 1e6 < 2s, sort 1e5 < 2s).
R21 Test suite: `tests/run_tests.sh` (or `make test`) runs every `tests/cases/*.lua` through `./lua` and compares stdout with `*.expected` (hand-derived from the manual), plus error/CLI tests (exit codes, stderr), plus Go unit tests for lexer/number formatting. Every example in the ticket is a test.
R22 README: what, install/build, run, test, design, limitations.

## Assumptions
- Go is installed (go 1.2x). Launcher `./lua` builds on demand; `make` also builds. Offline: no external modules.
- Tree-walking evaluator w/ resolved slots instead of bytecode (performance goal is "a few seconds").
- `__gc` no-op, `__mode` ignored, `collectgarbage("count")` returns Go heap KB.
- Stack depth: Lua call depth limit ~200 (C-like limit LUAI_MAXCCALLS) is NOT imposed; limit at ~200000 Lua frames raising "stack overflow" (goroutine max stack raised via debug.SetMaxStack).
- `string.format('%q')`, `%a` implemented as in C printf semantics; `os.date` implemented by hand (strftime subset).
- Integer-keyed float normalisation: float keys with integer value are converted to int keys.
- No `string.dump`, no real `debug` library beyond R19.
- Error "traceback" content is best-effort (function names and lines), format starts with `stack traceback:`.

## Test strategy
Lua-script case tests (R3-R19) with expected stdout derived from the manual; CLI tests via shell (R1, R2); error message tests via pcall (R11); Go unit tests (R4, R5); perf smoke tests with time limits (R20). Run by `make test`.

## Implementation notes (added in M3)
- Assumption: `string.format('%q', float)` always uses hexadecimal float notation (per the manual).
- Assumption: error messages mirror the manual/reference behaviour for the common cases (`bad argument #n to 'f' (...)`,
  `attempt to ... (local|global|field|upvalue|method|constant 'x')`).
- R20 is checked by `tests/perf/*.lua` with wall-clock limits inside `tests/run_tests.sh`; R22 is `README.md`.
