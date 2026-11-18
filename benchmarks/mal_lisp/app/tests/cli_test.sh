#!/bin/sh
# CLI-level tests for ./run (R1). Run from the workspace root.
cd "$(dirname "$0")/.." || exit 1
fail=0
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
check() { # name expected actual
    if [ "$2" != "$3" ]; then echo "FAIL $1: expected [$2] got [$3]"; fail=1; else echo "ok   $1"; fi
}

out=$(printf '(+ 1 2)\n' | STEP=step2_eval ./run)
case "$out" in "user> 3"*) echo "ok   step2 prompt+result";; *) echo "FAIL step2 output [$out]"; fail=1;; esac

out=$(printf 'foo\n(+ 1 2)\n' | STEP=step3_env ./run)
echo "$out" | grep -q "^user> Error: 'foo' not found$" && echo "ok   error line then continues" || { echo "FAIL error line [$out]"; fail=1; }
echo "$out" | grep -q "^user> 3$" || { echo "FAIL REPL did not continue [$out]"; fail=1; }

# EOF exits cleanly with status 0
printf '' | STEP=step0_repl ./run >/dev/null; check "EOF exit status" 0 $?

# unknown step -> non-zero
STEP=nosuchstep ./run </dev/null >/dev/null 2>&1; rc=$?
[ $rc -ne 0 ] && echo "ok   unknown step fails" || { echo "FAIL unknown step exit $rc"; fail=1; }

# no Go panic traces on odd input
out=$(printf '(\n"\n)\n[}\n(1 . 2)\n{1}\n' | STEP=step3_env ./run 2>&1)
echo "$out" | grep -q "goroutine" && { echo "FAIL panic trace"; fail=1; } || echo "ok   no panic traces"

# one result per line
out=$(printf '1\n2\n' | STEP=step1_read_print ./run)
check "one result per line" "user> 1
user> 2
user> " "$out"

# R9: ./run FILE ARGS... runs the file and binds *ARGV*
out=$(STEP=step6_file ./run tests/argv.mal a "b c" 3)
check "file mode with ARGV" '("a" "b c" "3")
3
3' "$out"
out=$(STEP=step6_file ./run tests/argv.mal)
check "file mode without args" '()
0
3' "$out"
out=$(STEP=step6_file ./run tests/argv.mal </dev/null)
case "$out" in *user\>*) echo "FAIL file mode printed a prompt"; fail=1;; *) echo "ok   file mode has no prompt";; esac
STEP=step6_file ./run tests/missing.mal >/dev/null 2>&1; rc=$?
[ $rc -ne 0 ] && echo "ok   missing file exits non-zero" || { echo "FAIL missing file rc=$rc"; fail=1; }

# R8/R15: deep recursion, tail and non-tail, from a file
cat > "$tmp/deep.mal" <<'MAL'
(def! sum2 (fn* (n acc) (if (= n 0) acc (sum2 (- n 1) (+ n acc)))))
(def! depth (fn* (n) (if (= n 0) 0 (+ 1 (depth (- n 1))))))
(prn (sum2 1000000 0))
(prn (depth 50000))
MAL
out=$(STEP=step6_file ./run "$tmp/deep.mal" 2>&1)
check "deep recursion" '500000500000
50000' "$out"

# R14: runaway recursion yields an Error line (no Go fatal error) and the REPL continues
out=$(printf '(def! f (fn* () (+ 1 (f))))\n(f)\n(+ 1 2)\n' | STEP=step5_tco ./run 2>&1)
case "$out" in *goroutine*|*"fatal error"*) echo "FAIL stack overflow crashed [$out]"; fail=1;; *'Error: stack overflow'*'user> 3'*) echo "ok   runaway recursion is an error";; *) echo "FAIL runaway [$out]"; fail=1;; esac

# Steps 4 and 5 expose the same core (spot check) and `not`
out=$(printf '(not nil)\n(str "a" 1)\n' | STEP=step4_if_fn_do ./run)
case "$out" in *"user> true"*'user> "a1"'*) echo "ok   step4 core";; *) echo "FAIL step4 core [$out]"; fail=1;; esac

# stepA: banner (REPL only), *host-language*, readline (prompt, answer, EOF -> nil)
out=$(printf '*host-language*\n' | STEP=stepA_mal ./run)
check "stepA banner and host language" 'Mal [Go]
user> "Go"
user> ' "$out"
out=$(printf '(readline "p> ")\nhello world\n(readline "q> ")\n' | STEP=stepA_mal ./run)
case "$out" in *'user> p> "hello world"'*'user> q> nil'*) echo "ok   readline";; *) echo "FAIL readline [$out]"; fail=1;; esac
out=$(STEP=stepA_mal ./run tests/argv.mal x)
case "$out" in "Mal"*) echo "FAIL banner in file mode"; fail=1;; *) echo "ok   no banner in file mode";; esac
out=$(printf '(+ 1 2)\n' | env -u STEP ./run)
check "default STEP is stepA_mal" 'Mal [Go]
user> 3
user> ' "$out"

# R16: self-hosting. The mal-in-mal stepA runs on the Go interpreter.
out=$(printf '(+ 1 2)\n(def! f (fn* (n) (if (= n 0) :done (f (- n 1)))))\n(f 5000)\n(try* (throw "boom") (catch* e (str "caught " e)))\nnope\n' | ./run mal/stepA_mal.mal)
check "self-hosted REPL" 'Mal [Go]
user> 3
user> #<function>
user> :done
user> "caught boom"
user> Error: '"'"'nope'"'"' not found
user> ' "$out"
out=$(./run mal/stepA_mal.mal tests/argv.mal a "b c")
check "self-hosted file mode with ARGV" '("a" "b c")
2
3' "$out"
# the self-hosted interpreter can run itself (mal in mal in mal) for a short program
cat > "$tmp/hello.mal" <<'MAL'
(prn (map (fn* (x) (* x x)) [1 2 3]))
MAL
out=$(./run mal/stepA_mal.mal mal/stepA_mal.mal "$tmp/hello.mal" 2>&1)
check "mal in mal in mal" '(1 4 9)' "$out"
exit $fail
