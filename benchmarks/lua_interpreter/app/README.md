# Lua 5.4 interpreter in Go

A from-scratch interpreter for the Lua 5.4 language and its standard libraries, written in Go with
no third-party dependencies and no code taken from any existing Lua implementation. The reference
manual in `docs/manual.of` is the normative specification.

## Install, run, test

Requirements: Go >= 1.21 (developed with 1.24) and a POSIX shell. Nothing else (no modules to download).

    ./lua script.lua a b     # builds bin/lua on first use (and whenever a .go file changed), then runs it
    make build               # or: go build -o bin/lua .
    make test                # go vet + go test + tests/run_tests.sh

CLI: `./lua [script [args]]`. `arg` is set (`arg[0]` = script, `arg[1..]`, negative index `-1` = "lua") and the
script receives the arguments as `...`. With no script (or `-`) the program is read from stdin; `-e chunk`
runs a chunk; `-v` prints the version. An uncaught error prints `lua: <message>` and a `stack traceback:` to
stderr and exits with status 1 (syntax errors likewise). `os.exit(n|true|false)` is honoured and flushes stdout.
`require` searches `package.path` (`./?.lua;./?/init.lua`) and additionally the directory of the main script.

## Tests

`make test` runs:

* `go test ./...` - unit tests for the lexer, number parsing/formatting, tables, parser errors, helpers (`core_test.go`).
* `tests/run_tests.sh` - runs every `tests/cases/*.lua` and compares stdout with the `.expected` file, then
  CLI tests (exit codes, stderr text, `arg`, stdin scripts, `io.read` on stdin, `os.exit`), then performance
  smoke tests (`tests/perf/`, wall-clock limits: `fib(25)` < 2 s, 1e6-iteration loops < 1 s, table/string workload < 3 s).
  Case files use `tests/cases/prelude.lua` (`eq`, `err`, `cerr` helpers). Expected values and error messages were
  derived from the manual, not recorded from this implementation.
* `tests/smoke/*.lua` are the scripts used by the verification smoke checks.

## Design

| File | Role |
|------|------|
| `lexer.go`, `parser.go`, `ast.go` | Lexer and recursive-descent parser. Scopes, local slots, upvalues, `goto` labels and `<const>`/`<close>` checks are resolved while parsing, so the AST already refers to variables. |
| `compile.go` | Turns the AST into Go closures (`func(*Frame) Value`, `func(*Frame) ctl`) - no bytecode. Captured locals live in `*Cell`s, others in frame slots (fresh cell per loop iteration). Control flow (`break`, `goto`, `return`, tail call) is returned as a status code. |
| `interp.go` | Frames, calls, proper tail calls (trampoline in `callLua`), error values (`panic(*LuaError)`), metamethod dispatch, arithmetic/comparison/concat semantics, `pcall`, tracebacks. |
| `table.go` | Tables: array part + insertion-ordered hash part (tombstones keep `next` valid while fields are cleared during traversal). |
| `value.go` | Value model (`interface{}`: nil, bool, int64, float64, string, `*Table`, `*Closure`, `*GoFunction`, `*Coroutine`, `*Userdata`); `%.14g` number formatting; numeral parsing (decimal, hex, hex floats). |
| `lib_base.go`, `main.go` | Base library, `package`/`require`, `load`, CLI. |
| `lib_string.go`, `lib_string_reg.go` | `string`: own Lua pattern matcher, C-style `format` (incl. `%q`, `%a`), `pack`/`unpack`/`packsize`. |
| `lib_table_math.go` | `table` (metamethod-aware) and `math` (xoshiro256** `random`). |
| `lib_utf8_co.go` | `utf8`, and `coroutine`: each coroutine runs on its own goroutine with channel hand-off, so yields work across `pcall`, iterators and nested calls; `coroutine.close` unwinds the goroutine and runs pending `<close>` handlers. |
| `lib_os.go`, `lib_io.go`, `lib_debug.go` | `os`, `io` (stdout is shared with `print`, so output ordering is preserved), a small `debug`. |

Key points: strings are Go byte strings (no encoding assumptions); integers are 64-bit and wrap; floats are
`float64`; variable names are recorded at compile time so errors read like
`file:3: attempt to index a nil value (field 'x')`. Call depth is limited to 200000 Lua frames (a catchable
`stack overflow` error) and the Go stack limit is raised accordingly; tail calls do not consume depth.

## Behaviour notes and limitations

* `__gc` is accepted but never called and `__mode` is ignored (no weak tables). `collectgarbage("count")` reports
  the Go heap in KB; `"collect"` runs a Go GC.
* `string.dump`, `io.popen`, `os.execute` and binary chunks are not supported (`load` of a binary chunk fails with a
  message). `debug` is a subset (`traceback`, `getinfo`, upvalue access, metatables; hooks and locals are no-ops).
* `goto` that jumps into the scope of a local is a compile error (a label at the very end of a block is exempt, as in the manual).
* `table.sort` does not detect inconsistent comparison functions ("invalid order function"); it never crashes.
* `os.clock` is process CPU time; `os.date`/`os.time` use the local time zone (`!` prefix = UTC).
* `io.write` formats floats like `tostring` (`1.0`). `%c` in `os.date` follows the C locale.
