# LANG-19: SPI — a Simple Pascal Interpreter (tree-walking, with semantic analysis and a call stack)

Implement a Python interpreter for a small Pascal subset, runnable as `./spi <file.pas> [--scope] [--stack]`.

## Language
* `PROGRAM <name>; <block> .` where a block is: optional `VAR` declarations (`a, b : INTEGER;`,
  `x : REAL;`), zero or more nested `PROCEDURE <name> [ ( <formal parameters> ) ] ; <block> ;`
  declarations (formal parameters grouped like `(a, b : INTEGER; c : REAL)`), then a compound statement.
* Statements: `BEGIN ... END` (statements separated by `;`, empty statements allowed), assignment `x := expr`,
  procedure calls, always with parentheses: `Name(arg, ...)` or `Name()`.
* Expressions: `+ - * /` (real division), `DIV` (integer division, truncating like Python `//` on the
  test inputs), unary `+`/`-`, parentheses, integer and real literals (`3.14`). Standard precedence.
* Keywords are case-insensitive; identifiers are case-sensitive, start with a letter and continue with
  letters or digits. `{ ... }` comments. Whitespace insensitive.
* At run time a procedure works only with its own parameters and local variables (programs that read
  variables of enclosing scopes are outside the supported subset).

## Semantic analysis (before execution)
Scoped symbol tables (built-in types INTEGER and REAL in the global scope; one scope per procedure).
Errors: declaring a variable twice in the same scope's VAR section, and using an undeclared variable. Procedure calls bind
actual arguments to formal parameters.

## Errors (print the message on stdout and exit with status 1)
Positions are `line:column`, 1-based, of the offending token / character.
```
LexerError: Lexer error on '<char>' line: <line> column: <col>
ParserError: Unexpected token -> Token(TokenType.<TYPE>, <value repr>, position=<line>:<col>)
SemanticError: Duplicate id found -> Token(TokenType.ID, '<name>', position=<line>:<col>)
SemanticError: Identifier not found -> Token(TokenType.ID, '<name>', position=<line>:<col>)
```
Token type names: PLUS MINUS MUL FLOAT_DIV LPAREN RPAREN SEMI DOT COLON COMMA PROGRAM INTEGER REAL
INTEGER_DIV VAR PROCEDURE BEGIN END ID INTEGER_CONST REAL_CONST ASSIGN EOF. `<value repr>` is the
Python repr of the token value (reserved words upper-cased, e.g. `'BEGIN'`; numbers as numbers, e.g. `5`, `3.14`).

## Execution trace (`--stack`)
Maintain a call stack of activation records (PROGRAM at nesting level 1, each procedure call one level
deeper). On entering/leaving the program and each procedure print exactly:
```
ENTER: PROGRAM Main
CALL STACK
1: PROGRAM Main

```
i.e. `ENTER: <TYPE> <name>` or `LEAVE: <TYPE> <name>`, then `CALL STACK`, then the records from the top
of the stack down, each as `<level>: <TYPE> <name>` followed by one line per variable/parameter in the
order they were first assigned: three spaces, the name left-justified to 20 characters, `: `, the value
(Python `str` formatting of int/float), then a blank line. Print the stack at `LEAVE` *before* popping.
`--scope` additionally prints scope entry/exit and symbol table contents (free format).

Deliverables: the interpreter, a test suite (lexer, parser, semantic analyzer, interpreter, CLI), README.
