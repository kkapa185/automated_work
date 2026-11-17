# SPI — Simple Pascal Interpreter (requirements)

## Product
A Python 3 CLI interpreter (`./spi <file.pas> [--scope] [--stack]`) for a small Pascal subset: lexer → parser (AST) → semantic analyzer (scoped symbol tables) → tree-walking interpreter with a call stack of activation records. Errors print to stdout and exit 1. Classification: compiler/interpreter toolchain; pure stdlib Python, pytest-free-capable tests (unittest-compatible, runnable via `python3 -m unittest` and pytest).

## Acceptance criteria
R1. `./spi file.pas` runs the program; exit 0 on success; no output without flags (no WRITE statement exists).
R2. Lexer: keywords PROGRAM VAR PROCEDURE BEGIN END INTEGER REAL DIV case-insensitive, token value upper-cased; identifiers case-sensitive (letters then letters/digits); `{...}` comments (may span lines); whitespace ignored; INTEGER_CONST (int value), REAL_CONST (float value, e.g. `3.14`); symbols + - * / ( ) ; . : , and `:=`.
R3. Token repr: `Token(TokenType.<TYPE>, <repr(value)>, position=<line>:<col>)`; types: PLUS MINUS MUL FLOAT_DIV LPAREN RPAREN SEMI DOT COLON COMMA PROGRAM INTEGER REAL INTEGER_DIV VAR PROCEDURE BEGIN END ID INTEGER_CONST REAL_CONST ASSIGN EOF. Positions 1-based line:column of token's first char.
R4. Lexer error: `LexerError: Lexer error on '<char>' line: <l> column: <c>`, exit 1.
R5. Grammar: `program : PROGRAM ID SEMI block DOT`; `block : [VAR declarations] procedure_decls compound`; at most one VAR keyword; second VAR → `ParserError: Unexpected token -> Token(TokenType.VAR, 'VAR', position=l:c)`. Declarations: `ID (COMMA ID)* COLON type SEMI` repeated (one or more). Procedure: `PROCEDURE ID [LPAREN params RPAREN] SEMI block SEMI`; params `ID(,ID)* : type (; ID(,ID)*: type)*`. Statements: compound, assignment, call `ID(args)` / `ID()`, empty. Expressions with precedence: `+ -` < `* / DIV` < unary `+ -` < literals/parens/variables.
R6. ParserError format: `ParserError: Unexpected token -> Token(TokenType.X, v, position=l:c)` for any unexpected token (including EOF), exit 1.
R7. Semantic: global scope has built-ins INTEGER, REAL; program scope "global"; each procedure own scope (enclosing = parent). Duplicate variable/param in same scope → `SemanticError: Duplicate id found -> Token(TokenType.ID, 'name', position=l:c)` (token of the second declaration). Undeclared variable used (as assignment target or in expression) → `SemanticError: Identifier not found -> Token(TokenType.ID, 'name', position=l:c)`. Lookup of variables walks enclosing scopes (analysis only). Calling an undeclared procedure → Identifier not found at the call-name token. Call arg count mismatch → assumption: SemanticError (see A4). Args are analyzed and bound to formal params.
R8. Interpreter: assignment evaluates expr; `/` always yields float; `DIV` is `//`; unary ops; int/real values. Procedure call evaluates args in the caller's AR, creates a new AR (level = caller level+1) with params bound in order, executes the body, pops. Variables only get a value when first assigned.
R9. `--stack`: on enter/leave print `ENTER: PROGRAM Main` / `LEAVE: PROGRAM Main` (`PROCEDURE` for procs), then `CALL STACK`, then records top→bottom `<level>: <TYPE> <name>` followed by lines `   ` + name.ljust(20) + `: ` + str(value) in first-assignment order (params first, in order, as they are assigned at call), then exactly two empty lines. Print at LEAVE before popping. Exact example: `ENTER: PROGRAM Main\nCALL STACK\n1: PROGRAM Main\n\n\n`.
R10. `--scope`: prints scope enter/leave and symbol table contents (free format) during semantic analysis. Flags combinable and in any order; output of scope precedes execution output.
R11. Errors go to stdout, exit 1. Missing file / bad usage → message on stderr, exit 2 (assumption).
R12. Runtime division by zero → `RuntimeError: ...` stdout exit 1 (assumption; not in spec).
R13. Deliverables: `spi` executable, package modules, tests (lexer, parser, semantic, interpreter, CLI), README, requirements doc.

## Assumptions
A1. Program name keeps original case in output (`PROGRAM Main`); identifiers case-sensitive, so `x` and `X` differ.
A2. Variable in AR printed with Python `str` of value (ints `5`, floats `2.5`, `7 / 2` → `3.5`; `4 / 2` → `2.0`).
A3. DIV truncation: Python `//`.
A4. Wrong arg count → `SemanticError: Wrong number of arguments -> Token(...)` at the call-name token, exit 1.
A5. Reading enclosing-scope variables at run time is out of scope; if it happens, treated as an uninitialized-variable RuntimeError. Reading an assigned-never variable → `RuntimeError`, exit 1.
A6. Type checking (INTEGER vs REAL assignment coercion) not performed; values stored as computed. 
A7. In a procedure's AR, params are printed first (in declaration order), then locals as first assigned.
A8. Lexer error position uses the offending character; unterminated `{` comment → LexerError on `{`.
A9. `3.` or `.5` : `3` integer then DOT; `.` handled as DOT token.
A10. Semantic analysis fully precedes execution, so semantic errors print nothing from `--stack`.

## Test strategy
- tests/test_lexer.py: tokens, case-insensitivity, positions, comments, reprs, lex errors (R2–R4).
- tests/test_parser.py: AST shape, double VAR, unexpected tokens, empty statements, call forms (R5, R6).
- tests/test_semantic.py: duplicates, undeclared, scopes, arg-count, --scope output sanity (R7, R10).
- tests/test_interpreter.py: arithmetic, precedence, DIV, `/`, unary, procedure calls, exact `--stack` byte output hand-derived from spec (R8, R9).
- tests/test_cli.py: subprocess runs of `./spi`, exit codes, error messages, flags (R1, R9–R11).
