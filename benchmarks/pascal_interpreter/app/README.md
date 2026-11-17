# SPI — Simple Pascal Interpreter

A tree-walking interpreter for a small Pascal subset, written in Python 3 (stdlib only).

## Language
`PROGRAM name; [VAR decls] {PROCEDURE name[(params)]; block;} BEGIN ... END.`
Statements: compound, assignment, procedure calls (`P(a, b)` / `P()`), empty statements.
Expressions: `+ - * /` (real division), `DIV` (floor division), unary `+ -`, parentheses, integer and real literals.
Keywords are case-insensitive, identifiers case-sensitive, `{ comments }` are skipped.
A procedure only sees its own parameters and locals at run time.

## Usage
```
./spi program.pas [--scope] [--stack]
```
* `--stack` prints `ENTER:`/`LEAVE:` lines plus the call stack (top first, variables in first-assignment order).
* `--scope` prints scope entry/exit and symbol table contents during semantic analysis.
* Errors (`LexerError`, `ParserError`, `SemanticError`, `RuntimeError`) are printed on stdout, exit status 1.
  Usage / unreadable file: message on stderr, exit status 2.

Example: `./spi examples/nested.pas --stack`

## Install / test
No dependencies (see `requirements.txt`). Run tests with `python3 -m unittest discover -s tests -t .`
(pytest also works).

## Design (package `spi_interp`)
`tokens` / `lexer` (lazy, position-tracking) → `parser` (recursive descent, AST in `ast`) →
`semantic` (scoped symbol tables from `symbols`; duplicate / undeclared / arity checks; binds calls to
procedure symbols) → `interpreter` (activation records + call stack) ; `cli` wires it together.
Lexing is on demand, so the first error in source order wins between lexer and parser.
The package is not named `spi` because that clashes with the `spi` executable.

## Assumptions
Division by zero and reading an unassigned variable are runtime errors (`RuntimeError: ...`).
Procedure calls with the wrong number of arguments give `SemanticError: Wrong number of arguments -> Token(...)`.
No int→float coercion on assignment to REAL variables. Unbounded recursion reports a runtime error.
