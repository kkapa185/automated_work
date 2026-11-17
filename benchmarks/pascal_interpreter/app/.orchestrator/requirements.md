# SPI — Simple Pascal Interpreter

## Product
A Python 3 (stdlib only) CLI interpreter, `./spi <file.pas> [--scope] [--stack]`, for a small Pascal subset
(PROGRAM, VAR, nested PROCEDUREs with params, assignments, procedure calls, arithmetic). Pipeline: lexer ->
parser (AST) -> semantic analyzer (scoped symbol tables) -> tree-walking interpreter with a call stack of
activation records. Classification: compiler/interpreter toolchain, CLI.

## Acceptance criteria
- R1 `./spi file.pas` runs the program; with no flags prints nothing on success (exit 0).
- R2 Lexer: case-insensitive keywords (PROGRAM VAR PROCEDURE BEGIN END DIV INTEGER REAL), case-sensitive
  identifiers (letter then letters/digits), `{}` comments (multi-line), whitespace-insensitive, INTEGER_CONST,
  REAL_CONST (`3.14`), tokens PLUS MINUS MUL FLOAT_DIV LPAREN RPAREN SEMI DOT COLON COMMA ASSIGN EOF. Line:col 1-based.
- R3 Lexer error: `LexerError: Lexer error on '<char>' line: L column: C`, stdout, exit 1.
- R4 Parser: grammar per spec; procedure calls always with parentheses (`Name()` allowed); empty statements allowed;
  formal params grouped `(a, b : INTEGER; c : REAL)`; nested procedures.
- R5 Parser error: `ParserError: Unexpected token -> Token(TokenType.X, repr, position=L:C)`; keywords uppercased in
  value; numbers as numbers; EOF value `None`. Exit 1.
- R6 Expressions: standard precedence, left-assoc, unary +/-, `/` real division, DIV integer truncating (`//`).
- R7 Semantic: scoped symbol tables, builtin INTEGER/REAL in global scope, one scope per procedure (params are in it).
  Duplicate var/param in same scope -> `SemanticError: Duplicate id found -> Token(TokenType.ID, 'x', position=L:C)`
  (position of the second declaration). Undeclared variable use (assignment target or expression) ->
  `SemanticError: Identifier not found -> Token(TokenType.ID, 'x', position=L:C)`. Calls to undeclared procedures
  and arity mismatch also errors (not-found uses same format; arity mismatch: SemanticError message with token).
  Calls bind actual args to formals (analysis checks arg expressions' variables).
- R8 Interpreter: variables initially unset; assignment stores values; integer vs real types: INTEGER
  var assigned from `/` stays float (no coercion beyond: declared REAL var assigned int stays int? — see assumptions).
- R9 `--stack`: byte-exact trace format at ENTER/LEAVE of program and each procedure call, levels from top down,
  variables in first-assignment order (params assigned at call in order), `   ` + name.ljust(20) + `: ` + str(value),
  followed by exactly two empty lines after the last record line. LEAVE prints before pop.
- R10 `--scope`: prints scope enter/leave and symbol table contents (free format) on stdout.
- R11 Errors exit status 1 with message on stdout; missing file/usage -> nonzero exit.
- R12 Tests: lexer, parser, semantic, interpreter, CLI; README.

## Assumptions
- Values keep Python types: `/` gives float, DIV gives int, no coercion on assignment (stack prints str(value)).
  Reading an unassigned variable yields no value; treated as runtime error `RuntimeError` message, exit 1.
- Procedure bodies see only own scope at runtime; semantic analyzer resolves names through enclosing scopes
  (lookup chain) as in standard Pascal, but runtime reads only own record.
- Arity mismatch: `SemanticError: Wrong number of arguments -> Token(TokenType.ID, 'P', position=L:C)`.
- `--scope` and `--stack` outputs: scope output first (during analysis), then stack trace during execution.
- Parser error token for unexpected EOF is `Token(TokenType.EOF, None, position=L:C)`.
- Name display in stack for procedure/program uses the declared (case-preserved) name.

## Test strategy
Unit tests (unittest) for lexer (R2,R3), parser (R4,R5), semantic (R7), interpreter (R6,R8), CLI via subprocess
(R1,R9,R10,R11) including byte-exact stack output comparison.
