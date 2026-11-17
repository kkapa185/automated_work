# SPI — Simple Pascal Interpreter: requirements

## Product
A Python 3 (stdlib only) tree-walking interpreter for a small Pascal subset (PROGRAM, VAR, nested PROCEDUREs with
parameters, assignment, procedure calls, arithmetic). Pipeline: Lexer -> Parser (AST) -> Semantic analyzer
(scoped symbol tables) -> Interpreter (call stack of activation records). CLI: `./spi <file.pas> [--scope] [--stack]`.
Kind: compiler/interpreter toolchain; tests via pytest/unittest (stdlib unittest, runnable by pytest too).

## Acceptance criteria
R1. `./spi file.pas` runs the program; with no flags prints nothing on success (exit 0). Missing file/args -> usage message, exit nonzero (2).
R2. Lexer: keywords PROGRAM VAR PROCEDURE BEGIN END INTEGER REAL DIV case-insensitive, token value upper-cased. Identifiers case-sensitive, letter then letters/digits. `{...}` comments skipped (may span lines). Whitespace insensitive. Integer (`INTEGER_CONST`, int value) and real (`REAL_CONST`, float value, e.g. `3.14`) literals. Symbols + - * / ( ) ; . : , := (types PLUS MINUS MUL FLOAT_DIV LPAREN RPAREN SEMI DOT COLON COMMA ASSIGN), EOF.
R3. Lexer error on unknown char: `LexerError: Lexer error on '<char>' line: L column: C` (stdout, exit 1), 1-based position of the char.
R4. Token repr: `Token(TokenType.<TYPE>, <repr(value)>, position=L:C)`; position = start of token.
R5. Parser grammar: program : PROGRAM ID SEMI block DOT; block : declarations compound; declarations : (VAR (var_decl SEMI)+)? (PROCEDURE ID (LPAREN formal_parameter_list RPAREN)? SEMI block SEMI)*; var_decl: ID (COMMA ID)* COLON type; formal params groups separated by SEMI; compound: BEGIN statement_list END; statements separated by `;`, empty allowed; assignment; call `ID(args)` / `ID()`; expr with + - (left-assoc), * / DIV, unary +/-, parens, literals, variables.
R6. Parser error: `ParserError: Unexpected token -> Token(TokenType.X, value, position=L:C)` of the offending token (including EOF, and tokens after the final DOT? — trailing content after DOT is ignored only if EOF expected: we require EOF after DOT, otherwise error on that token). Exit 1.
R7. Semantic: builtin INTEGER, REAL in global (builtins) scope; PROGRAM scope is level 1 (global scope holding program vars), one scope per procedure (parameters + locals). Duplicate declaration in same scope (VAR or parameter clash) -> `SemanticError: Duplicate id found -> Token(TokenType.ID, 'name', position=L:C)` of the duplicate's identifier token. Undeclared variable use (read or assign target) -> `SemanticError: Identifier not found -> Token(TokenType.ID, 'name', position=L:C)`. Lookup walks enclosing scopes (analysis only). Calls to undeclared procedures also -> Identifier not found. Reported before any execution output.
R8. Procedure calls: analyzer binds actual args to formal params (resolves procedure symbol; arity mismatch -> SemanticError-style message `SemanticError: Wrong number of arguments -> Token(TokenType.ID, 'name', position=L:C)`).
R9. Interpreter: INTEGER vars assigned int; `/` yields float; DIV is integer floor division (`//`); unary ops; REAL vars hold floats (an int assigned to REAL variable is stored as given/converted? — assumption: stored as computed Python value, no coercion, except none). Procedure call evaluates args in caller, creates new activation record at level caller+1 with params bound in order, runs body, pops. Procedures access only own AR.
R10. `--stack`: on entering/leaving program and each procedure prints `ENTER: <TYPE> <name>` / `LEAVE: <TYPE> <name>` (TYPE = PROGRAM or PROCEDURE), then `CALL STACK`, then each AR top-down as `<level>: <TYPE> <name>` and one line per member in first-assignment order: `   ` + name.ljust(20) + `: ` + str(value); then a blank line after each record (the whole stack ends with a blank line). Stack at LEAVE printed before pop. Format example:
```
ENTER: PROGRAM Main
CALL STACK
1: PROGRAM Main

```
Parameters are members in formal order, first assigned at call time. Printed output goes to stdout.
R11. `--scope`: prints scope entry/exit and symbol table contents to stdout (free format) during semantic analysis. Flags combinable, any order, relative to file arg.
R12. Errors printed to stdout, exit status 1; success exit 0.
R13. Deliverables: `spi` executable script, package `spi/` modules (lexer, parser, ast, symbols/semantic, interpreter, cli), tests/ (lexer, parser, semantic, interpreter, CLI), README.md, requirements.txt (empty/stdlib note).

## Assumptions
- Program name keeps source case (`Main`); procedure names too.
- Value strings use Python `str`; no int->float coercion for REAL variables (assigned value stored as computed). Division by zero is a runtime error: print `RuntimeError: Division by zero`, exit 1.
- Reading an unassigned variable at run time: error `RuntimeError: Variable '<name>' referenced before assignment`, exit 1.
- Duplicate position: the second occurrence identifier token. Parameters and var in same procedure clash.
- Call as statement only (no function calls in expressions). Call syntax requires parentheses.
- Non-terminating `.` followed by other tokens -> ParserError on first token after DOT (expected EOF).
- Lexer errors surface at the time the lexer reaches the char (parser pull-based), so a parser error earlier in the file wins; to be deterministic we lex lazily.

## Test strategy
Unit tests per stage (R2-R4 lexer, R5-R6 parser, R7-R8 semantic, R9 interpreter), CLI subprocess tests (R1, R3, R6, R7, R10-R12) including exact `--stack` output comparison, README check manual.
