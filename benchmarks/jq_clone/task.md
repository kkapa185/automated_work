# DATA-500: `jq` — command-line JSON processor (full implementation)

Build a complete, standalone implementation of the `jq` command-line JSON processor, executable as
`./jq` from the workspace root (any implementation language; no dependency on an existing jq
implementation, binary or library such as libjq, gojq, jaq or the `jq` Python bindings). The official jq
manual is provided in `docs/manual.yml` and is **normative**: the language, every builtin it documents
and every example in it must behave as described.

Scope:
* The full jq language: literals, `.`/paths/optional `?`, pipes, comma, parentheses, array/object
  construction (incl. shorthand `{a, $x, "b": 1, (.k): 2, @base64: ...}`), string interpolation and
  `@format` strings (`@text @json @html @uri @csv @tsv @sh @base64 @base64d`), arithmetic and comparison
  with jq's type ordering and semantics (object/array addition, string multiplication/division, etc.),
  `and/or/not`, alternative `//`, `if/elif/else/end`, `try/catch`, `error`, `label`/`break`, `reduce`,
  `foreach` (2- and 3-arg), function definitions with filter and `$`-parameters, recursion,
  variables, destructuring (incl. `?//` alternatives), `$__loc__`, `..`, assignment operators (`=`, `|=`,
  `+=`, `-=`, `*=`, `/=`, `%=`, `//=`), `limit`, `first/last/nth`, `until`, `while`, `repeat`, `range/1,2,3`,
  `path`, `paths`, `getpath/setpath/delpaths`, `to_entries/from_entries/with_entries`, `select`, `empty`,
  `recurse`, `env/$ENV`, `input/inputs`, `splits/sub/gsub/test/match/capture/scan` (Oniguruma-style
  regexes with flags), math builtins, `tostring/tonumber/tojson/fromjson`, dates (`strftime`, `mktime`,
  `gmtime`, `todate`, `fromdate`, `strptime`, `dateadd`...), `getpath`, `splits`, `ltrimstr/rtrimstr`,
  `ascii_downcase`, `implode/explode`, `group_by/unique_by/min_by/max_by/sort_by`, `combinations`,
  `walk`, `transpose`, `in/inside/contains/has/index/rindex/indices`, `tojson` number formatting, `@sh`
  quoting, `getpath`, `ltrimstr`, `splits`, `abs`, `toarray`, `pick`, `have_literal_numbers` etc. — i.e.
  everything in the manual.
* CLI options: `-n`, `-r`, `-j`, `-a`, `-c`, `-s`, `-e`, `-S`, `--tab`, `--indent n`, `--arg`, `--argjson`,
  `--slurpfile`, `--rawfile`, `--args`, `--jsonargs`, `-f file`, `--raw-input/-R`, `--seq`,
  `--exit-status`; multiple JSON values on stdin; files as arguments.
* Output formatting identical to jq: 2-space pretty printing by default, `-c` compact form, number
  formatting (`1.0` prints as `1.0`, large/small numbers like jq 1.7+), key order preserved,
  `-S` sorts keys.
* Error messages on stderr in jq's style (`jq: error (at <stdin>:0): ...`) and exit codes (5 for runtime
  errors, 2/3 for usage/compile errors).

Deliverables: the implementation, a test suite (unit tests per builtin plus all manual examples as
end-to-end tests), and a README.
