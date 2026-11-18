# jq clone (Python)

A standalone implementation of the `jq` JSON processor (jq 1.7/1.8 semantics, following the
normative manual in `docs/manual.yml`). Pure Python 3 (stdlib only); no jq library is used.

## Run
    ./jq '.a | map(. * 2)' input.json
    echo '{"a":[1,2]}' | ./jq -c .

Supported options: `-n -r -j -a -c -s -e -S -C -M --tab --indent n --arg --argjson --slurpfile
--rawfile --args --jsonargs -f/--from-file -R/--raw-input --seq --stream --raw-output0 -L -V -h`.
Exit codes: 0 ok, 1/4 with `-e`, 2 usage/input errors, 3 compile errors, 5 runtime errors.

## Install / test
    pip install -r requirements.txt      # pytest + PyYAML (tests only; the tool needs nothing)
    make test                            # or: python3 -m pytest tests -q

The suite has the 259 manual examples (`tests/test_manual.py`, read directly from the YAML),
per-builtin tests, language tests and CLI tests.

## Design (`jqpy/`)
- `lexer.py`, `parser.py`: tokenizer (string interpolation is lexed recursively) and recursive-descent
  parser producing a tuple AST with jq's precedence rules.
- `interp.py`: compiles the AST to Python generator closures `fn(env, path, value)` yielding
  `(path, value)`; one evaluator serves both normal and path-tracking mode (`path()`, assignment, `del`).
  Core semantics: ordering/arithmetic, getpath/setpath/delpaths, destructuring incl. `?//`, label/break.
- `builtins.py`: native builtins, special forms (limit, first, range, until, ... implemented iteratively
  so deep streams do not recurse) and a jq-language prelude compiled lazily.
- `values.py`: JSON parse/serialise. Number literals keep their canonical decimal text (`1.0`, big ints)
  until arithmetic; other doubles print in jq's shortest form.
- `regexfn.py` (Oniguruma syntax translated to `re`), `dates.py` (strftime/strptime/ISO 8601),
  `formats.py` (`@csv`, `@sh`, ...), `modules.py` (import/include/modulemeta), `cli.py`.

## Assumptions
- `@html` escapes `'` as `&apos;` as written in the manual; `have_decnum` is true (literals preserved).
- `repeat(f)` is `f | (., repeat(f))` with one-output lookahead so the manual example works.
- Bessel functions (`j0 j1 y0 y1 jn yn`) raise "not available" (the manual allows this).
