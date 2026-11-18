# LANG-54: A Lua 5.5 interpreter

Implement a complete interpreter for the Lua 5.5 language and its standard libraries, executable as
`./lua [script [args]]` from the workspace root (any implementation language except Lua itself; do not
wrap, embed or port an existing Lua implementation such as PUC-Lua/liblua, LuaJIT, gopher-lua, moonsharp,
fengari or lupa). The Lua 5.5 Reference Manual is provided in `docs/manual.of` and is **normative** (Lua 5.5, not 5.4: e.g.
`global` declarations such as `global <const> *`, `global x, y`, and the 5.5 rules for undeclared globals and
loop variables are part of the language).

Scope:
* The whole language: all value types (nil, boolean, integer/float subtypes with Lua 5.4 conversion
  and formatting rules, strings as byte arrays, tables with array/hash parts, functions, coroutines),
  lexical rules (long strings/comments, escapes incl. `\z`, `\x`, `\u{...}`, numerals incl. hex floats),
  all operators with correct precedence (integer division, floor modulo, bitwise ops, `..`, `#`),
  local and global declarations with attributes `<const>`/`<close>` (Lua 5.5 `global` statement), varargs, multiple assignment/returns, closures/upvalues,
  `goto`/labels, numeric and generic `for`, proper tail calls, metatables and all metamethods
  (`__index __newindex __call __eq __lt __le __concat __len __unm __add`..., `__close`, `__gc` may be a
  no-op, `__mode` may be ignored, `__name`, `__tostring`, `__pairs`), error values and messages with
  position information (`file:line: message`), `pcall`/`xpcall`/`error` with levels.
* Standard libraries: base (`print, type, tostring, tonumber` with bases, `pairs, ipairs, next, select,
  rawget/rawset/rawequal/rawlen, setmetatable/getmetatable, assert, error, pcall, xpcall, load` with
  text chunks and env, `dofile, require` for local modules, `collectgarbage` stubs), `string` (all
  functions incl. Lua patterns `find/match/gmatch/gsub`, `format` with all specifiers, `rep, byte, char,
  reverse, upper, lower, len, sub, pack/unpack/packsize`), `table` (`insert, remove, concat, sort` with
  comparator, `unpack, pack, move`), `math` (incl. `tointeger, type, ult, fmod, modf, huge, maxinteger`,
  `random`/`randomseed`), `utf8`, `coroutine` (`create, resume, yield, status, wrap, isyieldable,
  running, close`), `os` (`time, clock, date, getenv, exit`), `io.write/io.read/io.lines` on stdout/stdin
  and files.
* `./lua script.lua a b` sets `arg`; uncaught errors print `lua: <message>` plus a stack traceback to
  stderr and exit with status 1. Performance: recursive `fib(25)` and a 1e6-iteration loop in a few
  seconds.

Deliverables: the interpreter, a test-suite, a README.
