# LANG-88: "mal" — Make-A-Lisp interpreter, all steps through self-hosting

Implement the complete mal (Make-A-Lisp) language, a Clojure-inspired Lisp, following the official
step-by-step process. The process guide and the per-step pseudocode are provided in `docs/guide.md` and
`docs/step*.txt`; they are **normative**. Choose any implementation language available here (Python,
JavaScript/Node, Go, Rust, C, ...); do not reuse or port code from existing mal implementations.

Runtime contract (the standard mal convention): an executable `./run` at the workspace root starts the
REPL for the step named in the `STEP` environment variable (default `stepA_mal`), e.g.
`STEP=step4_if_fn_do ./run`. Each step must exist as a separate entry point —
`step0_repl, step1_read_print, step2_eval, step3_env, step4_if_fn_do, step5_tco, step6_file,
step7_quote, step8_macros, step9_try, stepA_mal` — and each step's REPL must behave exactly as that
step specifies (prompt `user> `, one result printed per line, errors reported as in the guide and
the REPL continues). `./run FILE ARGS...` runs a mal program (step6+), binding `*ARGV*`.

Required: reader/printer (all literal types incl. strings with escapes, keywords, vectors, hash-maps,
comments, reader macros `' \` ~ ~@ @ ^`), environments, special forms (`def! let* do if fn* quote
quasiquote quasiquoteexpand defmacro! macroexpand try* catch*`), tail-call optimisation (deep recursion
must not overflow), closures, the full core namespace of stepA (`prn str println pr-str read-string slurp
eval atom deref reset! swap! cons concat vec nth first rest list? count apply map throw symbol keyword
hash-map assoc dissoc get contains? keys vals sequential? meta with-meta fn? macro? string? number? seq
conj time-ms readline *host-language* ...`), metadata, and the self-hosting requirement: the mal
implementation written in mal itself must run on top of your interpreter.

Deliverables: the implementation, a test-suite (per step), a README.
