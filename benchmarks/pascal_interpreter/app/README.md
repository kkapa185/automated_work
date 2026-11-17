# SPI — Simple Pascal Interpreter

A tree-walking interpreter for a small Pascal subset, in Python 3 (standard library only; no install step).

    ./spi program.pas [--scope] [--stack]

## Language
`PROGRAM Name; [VAR decls] {PROCEDURE P [(a, b : INTEGER; c : REAL)]; block;} BEGIN ... END.`
Statements: compound, assignment (`:=`), procedure call with mandatory parentheses (`P(1, x)`, `P()`), empty.
Expressions: `+ - * / DIV`, unary `+ -`, parentheses, integer and real literals. Keywords are case-insensitive,
identifiers case-sensitive, `{ comments }` supported. Procedures are declared before use and, at run time,
see only their own parameters/locals.

## Flags
* `--stack` prints `ENTER:`/`LEAVE:` lines with the call stack (top first; variables in first-assignment
  order, `   name` padded to 20 chars, `: value`; two blank lines after each dump; LEAVE dumps before popping).
* `--scope` prints scope entry/exit and symbol table contents during semantic analysis.

## Errors
Printed on stdout, exit status 1: `LexerError`, `ParserError`, `SemanticError` (duplicate id, identifier not
found, wrong number of arguments) in the spec formats. A `RuntimeError` is raised for reading an unassigned
variable or dividing by zero. Usage errors/unreadable files exit non-zero (2 / 1) with a message on stderr.

## Design (`spi.py`)
Lexer → recursive-descent Parser (AST) → SemanticAnalyzer (`ScopedSymbolTable` chain; resolves procedure
calls to `ProcedureSymbol`s) → Interpreter (`CallStack` of `ActivationRecord`s). Values keep Python types
(`/` gives float, `DIV` gives int); there is no type coercion on assignment.

## Tests
    python3 -m unittest discover -s tests -v

Tests (`tests/test_spi.py`) cover lexer, parser, semantic analyzer, interpreter and CLI; names carry the
requirement numbers from `.orchestrator/requirements.md`. `examples/nested.pas` is a sample program.
