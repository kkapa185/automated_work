# SPI — a Simple Pascal Interpreter

A tree-walking interpreter for a small Pascal subset, written in pure Python 3 (stdlib only, no install step).
Pipeline: lexer → recursive-descent parser (AST) → semantic analyzer (scoped symbol tables) → interpreter with a call stack of activation records.

## Usage

    ./spi <file.pas> [--scope] [--stack]

* `--stack` prints `ENTER:`/`LEAVE:` lines and the call stack (top first; each record followed by its variables, in order of first assignment, as `   <name padded to 20>: <value>`; two empty lines after the stack; printed at LEAVE before popping).
* `--scope` prints scope entry/exit and symbol table contents during semantic analysis (free format).
* Lexer, parser, semantic and runtime errors are printed on stdout, exit status 1. Usage errors / unreadable file: message on stderr, exit 2.

Example (`examples/nested.pas`): `./spi examples/nested.pas --stack`.

## Language

```
program   : PROGRAM ID SEMI block DOT
block     : [VAR (ID (COMMA ID)* COLON type SEMI)+] procedure* compound
procedure : PROCEDURE ID [LPAREN params RPAREN] SEMI block SEMI
statement : compound | ID ASSIGN expr | ID LPAREN [expr (COMMA expr)*] RPAREN | empty
expr      : term ((PLUS|MINUS) term)* ;  term : factor ((MUL|DIV|/) factor)*
factor    : (PLUS|MINUS) factor | number | LPAREN expr RPAREN | ID
```
Keywords are case-insensitive, identifiers case-sensitive, `{...}` comments. `/` is real division, `DIV` is `//`.
A second `VAR` in a block is a ParserError at that token.

## Tests

    python3 -m unittest discover -s tests     # or: pytest tests

Files: `test_lexer`, `test_parser`, `test_semantic`, `test_interpreter`, `test_cli`; test names carry the requirement ids from `.orchestrator/requirements.md`.

## Design / assumptions

Modules in `spi_interp/`: `lexer`, `ast_nodes`, `parser`, `semantic` (symbols + analyzer), `interpreter` (call stack), `cli`.
At run time a procedure sees only its own activation record (params + locals); reading enclosing-scope variables is unsupported. Reading a never-assigned variable, or division by zero, gives `RuntimeError: ...` (exit 1). Calling a procedure with the wrong number of arguments gives `SemanticError: Wrong number of arguments -> Token(...)`. Duplicate procedure names in one scope are reported as duplicate ids. No type coercion between INTEGER and REAL is performed. See `.orchestrator/requirements.md` for the full list.
