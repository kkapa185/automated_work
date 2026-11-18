# mal — Make-A-Lisp in Go

A complete implementation of [mal](docs/guide.md), a Clojure-inspired Lisp, built from the
process guide and pseudocode in `docs/` (steps 0 – A), **including self-hosting**: a mal interpreter
written in mal (`mal/stepA_mal.mal`) runs on top of the Go interpreter and passes the same test-suite.

## Requirements / install

Only Go (1.22+; developed with 1.24) and `make`/`sh`. No third-party dependencies (`go.mod` has none).
Nothing to install: `./run` builds what it needs on demand.

## Run

```
./run                          # REPL of stepA_mal (prints "Mal [Go]", prompt "user> ")
STEP=step4_if_fn_do ./run      # REPL of any step: step0_repl step1_read_print step2_eval step3_env
                               #   step4_if_fn_do step5_tco step6_file step7_quote step8_macros
                               #   step9_try stepA_mal
./run FILE ARG...              # run a mal program (step6+), *ARGV* = (ARG...)
./run mal/stepA_mal.mal        # the self-hosted interpreter: REPL of mal-in-mal
./run mal/stepA_mal.mal FILE   # ... or run a program with it
```
A step with a file argument runs the file and exits (errors go to stderr, exit status 1).
Steps 0–5 ignore file arguments, as specified.

## Test

```
make test        # unit tests + CLI tests + every step's tests + self-hosted tests (≈3 min, mostly self-hosting)
make test-unit   # go test (reader, printer, env, equality)
make test-cli    # tests/cli_test.sh: run script, EOF, file mode, ARGV, deep recursion (1,000,000 tail calls), readline, self-hosting
make test-steps  # bin/runtests -step <step> for every step
make test-self   # stepA tests through mal-in-mal (./run mal/stepA_mal.mal)
```
`tools/runtests` is a small black-box runner for the standard mal test format: an input line, optional
expected-output lines (`;text`), then `;=>result` (exact) or `;/regex` (whole-output match); `;;` is a comment.
It feeds one line at a time and waits for the next `user> ` prompt. `-step S` selects the test files
(`tests/<step>*.mal`; step N ≥ 2 also replays the files of steps 2..N-1), `-impl "cmd"` changes the program under test.
Test vectors were derived by hand from the guide, not by running the implementation.

## Design

* `internal/mal` — shared library: `types.go` (values: `Nil`, `bool`, `int`, `string`, `Symbol`, `Keyword`,
  `*List`, `*Vector`, insertion-ordered `*HashMap`, `*Func`, `*Atom`; metadata on all collections and functions),
  `reader.go` (the guide's tokenizer regex + recursive descent), `printer.go`, `env.go`, `core.go`/`core2.go`
  (the core namespace), `evalutil.go` (helpers shared by the EVALs: let* bindings, closures,
  quasiquote expansion, macro expansion, `try*`), `repl.go`.
* `cmd/<step>/main.go` — one program per step, each with its own `READ/EVAL/PRINT/rep` exactly as the
  step's pseudocode (`run` builds `bin/<step>`). From step 5 EVAL is a loop (tail-call optimisation for
  `let* do if`, quasiquote and function calls; macros expand inside the loop).
* Errors are Go panics carrying a mal value (`*MalError`); `try*` uses `recover`, native errors
  (type errors, bad arguments, division by zero, Go runtime errors) become message strings. The REPL prints
  `Error: <message>` and continues (non-string throws print with `pr-str`). The Go stack limit is raised so deep
  non-tail recursion (tens of thousands of frames) works.
* `mal/stepA_mal.mal` — the self-hosted interpreter (reader, printer, environments, EVAL with TCO, macros,
  quasiquote, try*, metadata, REPL). Guest data are host values; guest functions are host closures carrying
  a metadata record for the TCO loop; guest tail calls are host tail calls. Hot paths avoid the `cond` macro
  (the host re-expands macros on every evaluation). The file contains literal TAB/CR characters in two strings
  because mal strings only know the `\n`, `\"` and `\\` escapes.

## Assumptions / notes

See `.orchestrator/requirements.md` (A1–A19). Notably: `*host-language*` is `"Go"`; `(load-file f)` returns `nil`
(per the step 6 pseudocode); arithmetic and comparisons are binary; `count` takes a list, vector or nil;
quasiquote does not track nesting levels (as in the guide); uncaught string exceptions print raw after `Error: `.
Runaway non-tail recursion raises a catchable "stack overflow" error (depth cap 400,000 nested evaluations).
Self-hosted execution is ~100x slower than native, so the `.mal` tests use loops of 10⁴–10⁵ iterations
while the CLI test exercises 10⁶ natively.
