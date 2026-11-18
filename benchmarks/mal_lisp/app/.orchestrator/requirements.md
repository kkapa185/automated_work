# Requirements — mal (Make-A-Lisp) interpreter, steps 0–A, self-hosting

## Product
A Clojure-inspired Lisp interpreter ("mal") written in Go, built strictly from `docs/guide.md` and `docs/step*.txt`
(normative). Eleven separate step entry points (step0_repl … stepA_mal) share a library (reader, printer, types, env,
core) but each has its own `main` with its own READ/EVAL/PRINT/rep. `./run` (shell script at workspace root) builds
(if needed) and execs the binary for `$STEP` (default `stepA_mal`); `./run FILE ARGS...` runs a mal program (step6+)
binding `*ARGV*`. A mal-in-mal implementation (`mal/stepA_mal.mal` etc., written by me from the guide) must run on top
of the interpreter and pass the same tests. Deliverables: implementation, per-step test suite, README.

## Acceptance criteria
R1  `./run` launches the REPL of step `$STEP` (default stepA_mal); unknown STEP → error exit non-zero. Prompt is `user> `;
    one result per line; EOF (Ctrl-D) exits cleanly. Binaries are built automatically from a clean checkout (needs only Go).
R2  step0: REPL echoes input unchanged (READ/EVAL/PRINT are identity).
R3  step1 reader: integers (incl. negative), symbols, nil/true/false, strings with escapes `\"` `\\` `\n`, keywords (`:a`),
    lists `()`, vectors `[]`, hash-maps `{}`, comments `;`, whitespace/commas, reader macros `'` `` ` `` `~` `~@` `@` `^`
    (`^meta form` → `(with-meta form meta)`). Unbalanced forms → `Error: ... unbalanced` style error (message contains
    "unbalanced" / "EOF"); REPL continues. Empty/comment-only line yields no output and continues.
R4  printer: `pr_str` readably (strings quoted+escaped) and `str` non-readably; keywords print `:k`; hash-maps `{"a" 1}`;
    functions `#<function>`; atoms `(atom 1)`; round-trip of read/print for all literals.
R5  step2: eval of arithmetic `+ - * /` (integer division); vectors/hash-map values evaluated; unknown symbol →
    `'x' not found`; error format `Error: msg`; REPL continues after errors. e.g. `(+ 1 2)`→`3`, `(/ (- (+ 5 (* 2 3)) 3) 4)`→`2`.
R6  step3: `def!`, `let*` (list or vector bindings, nested scoping), Env with outer chain; `DEBUG-EVAL` support.
R7  step4: `if` (nil/false falsy, 0 and "" truthy), `do`, `fn*` closures, `&` rest args, core: `list list? empty? count = < <= > >=
    prn pr-str str println not`; `=` compares lists and vectors element-wise as equal, deep, maps by contents.
R8  step5: TCO for `let* do if fn*` bodies: `(def! sum2 (fn* (n acc) (if (= n 0) acc (sum2 (- n 1) (+ n acc)))))` with n=10000
    (and 1,000,000) must not overflow; mutual recursion in tail position too.
R9  step6: `read-string slurp eval atom atom? deref reset! swap!` (`@a`), `load-file`, `*ARGV*`, `./run file args…` runs file then exits;
    `(load-file "x")` result nil handling per guide; `not`, `cond`-less step6 per guide.
R10 step7: `cons concat vec`, `quote`, `quasiquote`, `quasiquoteexpand`, `unquote`, `splice-unquote` (incl. vectors,
    nested) per the guide's rules; reader macros `` ` ~ ~@ ``; `nth first rest` (nil-tolerant).
R11 step8: `defmacro!`, `macroexpand`, `macro?` handling, `cond` and `or`-style macros defined in mal; `nth/first/rest` error on out-of-range
    as specified (`nth` out of range throws).
R12 step9: `try*/catch*`, `throw` of any mal value, native errors catchable as strings; core `apply map nil? true? false? symbol? symbol keyword
    keyword? vector? vector sequential? hash-map map? assoc dissoc get contains? keys vals`; uncaught throw prints `Error: <pr_str of value>`.
R13 stepA: `readline`, `*host-language*` ("Go"), `time-ms`, `meta with-meta` (functions, lists, vectors, maps; with-meta copies, doesn't mutate),
    `fn? string? number? seq conj`, `macro?`; startup banner `Mal [Go]` in REPL mode only; `(def! *host-language* ...)`; `swap!` etc.
    `conj` on list prepends, vector appends; `seq` per guide (list/vector/string/nil/empty→nil).
R14 Errors: all runtime errors (type errors in builtins, wrong arg counts, divide by zero, unknown symbol, bad syntax)
    are mal exceptions catchable by `try*` and printed as `Error: ...` in the REPL; the interpreter never crashes with a Go panic/stack trace.
R15 Deep recursion non-tail (e.g. depth ~10000 `(def! f (fn* (n) (if (= n 0) 0 (+ 1 (f (- n 1))))))`) works (Go stack raised); infinite loops not required.
R16 Self-hosting: `mal/` directory contains a mal implementation of stepA_mal written in mal (reader, printer, env, core wrappers over
    host primitives, EVAL with TCO, macros, try*, quasiquote). `STEP=stepA_mal ./run mal/stepA_mal.mal` gives a working REPL
    (`user> `) and runs the stepA test-suite, incl. running `./run mal/stepA_mal.mal file.mal` and nested `(load-file)`.
    Also runs the earlier steps' tests (it is stepA superset).
R17 Test-suite: per-step test files `tests/stepN_*.mal` in the standard mal format (`;; comment`, input line, `;=>` expected output,
    `;/` regex output lines, `;>>> ` directives optional) plus a Python-free runner (`tests/run_tests.sh` or Go test) that executes each file against
    its step REPL, supports `STEP`-selection and a self-hosted mode (`MAL_IMPL`). Every example in docs/guide.md and docs/step*.txt becomes a test.
    `make test` runs all steps; `make test-self` runs stepA tests through mal-in-mal.
R18 Print-length: `prn` returns nil and prints readably, `println` non-readably joined by spaces, `str` concatenates w/o spaces, `pr-str` joined by spaces readably.
R19 Hash-map keys may be strings or keywords (distinct from each other); `assoc/dissoc` are non-mutating; `keys/vals` order consistent (insertion order kept).
R20 README: what/install/run/test/design/assumptions.

## Assumptions
A1 Language Go (available at /usr/local/go; no external deps, standard library only; go.mod pins Go version). No readline lib: line editing via plain stdin; `readline` prints prompt and reads a line (nil on EOF).
A2 Each step is `cmd/<step>/main.go`; `./run` does `go build` into `bin/<step>` if missing or sources newer.
A3 Where the guide is silent (e.g. exact error texts) I use messages similar to `'x' not found`, `Error: ...`; tests only match on guide-specified text (using `;/` regex for variable messages).
A4 Integer type is int64; division by zero is a catchable error.
A5 The mal-in-mal is my own writing from pseudocode; it relies on host primitives for I/O (`readline`, `slurp`, `println`) and regex-free tokenising implemented in mal using string primitives (`subs`-style helpers are NOT in core; I will add only guide-listed functions: tokenising may use a host-provided `read-string`-independent approach — assumption: mal reader in mal reimplemented using `seq`/`nth`/`str` character loops).
A6 Hash-map ordering: insertion order. Atom `swap!` passes args per guide.
A7 `./run` with step < 6 and a file arg: ignores/treated as REPL per those steps (no file support).

## Test strategy
- R2–R13, R18, R19: step test files (`tests/stepN_*.mal`) executed against the real REPL binaries via the runner (black box).
- R14, R15, R8: dedicated test cases (deep recursion, error catch, panics) in the step tests plus `tests/extra_*.mal`.
- R1, R9: shell-level tests (`tests/cli_test.sh`): default STEP, unknown STEP, file+ARGV, EOF exit.
- R16: `make test-self` reruns stepA/step tests with `MAL_IMPL="./run mal/stepA_mal.mal"`.
- Go unit tests for reader/printer (`go test ./...`): known-answer strings computed by hand from the guide.

## Assumptions added in M1
A8 Uncaught string exceptions print as `Error: <raw string>`; other values as `Error: <pr_str>` (R12 text refines accordingly).
A9 `./run` with the default STEP=stepA_mal fails (unknown step) until M3 creates `cmd/stepA_mal`; steps ≥1 tests select via `bin/runtests -step`.
A10 Test runner (`tools/runtests`) runs step0/step1 tests only against their own step and step2..N tests cumulatively for step N≥2.
A11 Go package lives in `internal/mal` (the top-level `mal/` directory is reserved for the mal-in-mal sources).

## Assumptions added in M2
A12 `load-file` follows the step6 pseudocode (appends `nil`), so `(load-file "f")` prints `nil` (the guide prose's `9` is from an older revision).
A13 `./run FILE` prints an uncaught error to stderr and exits 1; success exits 0. `read-string` of blank/comment-only text returns nil.
A14 Core functions are shared (`internal/mal/core.go`), so steps 4/5 also contain step-6 functions that their spec doesn't list; harmless superset. User closures carry `Fn` (calls EVAL) plus Env/Params/Body for TCO.
A15 Test files may use `;text` lines for expected stdout lines (including empty ones).

## Assumptions added in M3
A16 Step binaries 7..A are generated-by-hand copies of the same EVAL shape; `quasiquoteexpand` is available from step7, `defmacro!`/`macroexpand`/`cond` from step8, `try*` from step9, banner/`*host-language*` in stepA only.
A17 Quasiquote follows the guide exactly (no nesting-level tracking). `+ - * /` and comparisons are strictly binary (guide: "first two parameters"); `count` accepts list/vector/nil only.
A18 `readline` tests live in `tests/cli_test.sh` (they need extra stdin lines the line-oriented runner cannot supply).
A19 Native (Go-side) errors are caught by `try*` as message strings; `conj` on nil yields a list; `with-meta` works on list/vector/map/function (not atoms).

## Notes added in M4
A20 Self-hosting is delivered as a single file `mal/stepA_mal.mal` (stepA superset; earlier-step files are not duplicated). Core functions that need no change are the host's own; printing, reading, env, EVAL, macros, quasiquote and try* are implemented in mal.
A21 `.mal` tests use ≤10⁵ iteration loops so the self-hosted run completes; the 10⁶-iteration tail-call test (R8) lives in `tests/cli_test.sh` and runs natively.
A22 `make test` includes `make test-self` (R16) and takes a few minutes.

## Review fixes
A23 Nested EVAL depth is capped at 400,000 (`mal.MaxDepth`); beyond that a catchable `stack overflow: recursion too deep` error is raised instead of a fatal Go stack overflow (R14/R15). Tail calls are unaffected. Applies to steps 4–A (steps 2–3 cannot define functions).
