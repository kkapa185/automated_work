# AGC-42: Assembler for the Apollo Guidance Computer (Block II) — assemble the Apollo 11 flight software

## Background
The workspace contains `agc_source/Comanche055/` (Command Module, "Colossus 2A") and
`agc_source/Luminary099/` (Lunar Module, "Luminary 1A"): the complete Apollo 11 flight software as
transcribed from the original YUL/GAP assembly listings. Each program has a `MAIN.agc` that pulls in every
other file in listing order with `$FILENAME.agc` include lines. The source uses the original Block II AGC
assembly language: basic and extended (`EXTEND`-prefixed) machine instructions, the many assembler
pseudo-operations (address/bank/block control, constants, equates, erasable assignments, checksums, ...),
and the *interpretive language* (packed interpreter opcodes and their operand words).

## What to build
A command-line assembler that turns either program into its fixed-memory ("core rope") image.

Entry point (any implementation language, but it must be runnable from the workspace root):
```
./agcasm assemble agc_source/Comanche055/MAIN.agc -o out/Comanche055.binsource [--symbols out/Comanche055.symbols.json] [--listing out/Comanche055.lst]
```
* Exit code 0 when the program assembles; non-zero with clear `file:line: message` diagnostics otherwise.
  Diagnostics for problems in the input must not crash the assembler.
* `--symbols` writes a JSON object mapping every symbol defined in the program to
  `{"value": <int>, "kind": "fixed"|"erasable"|"constant", "bank": <int or null>, "file": ..., "line": ...}`.
  For fixed-memory labels, `value` is the address as printed in YUL listings (e.g. 4000-7777 octal for
  switchable fixed in bank-relative form, with `bank` giving the fixed bank); for erasable labels the
  erasable address (with `bank` the erasable bank where applicable).
* `--listing` writes a human-readable listing: for each source line, the location, the generated word(s) in
  octal, and the source text.

### Rope output format (`.binsource`)
Plain text. Lines starting with `;` are comments and blank lines are ignored. The image consists of the 36
fixed banks (octal bank numbers 00-43) in the order `02, 03, 00, 01, 04, 05, ... 43` (i.e. the two
fixed-fixed banks 02 and 03 first, then all others ascending). Each bank starts with a header line
`BANK=<octal bank number without leading zero>` (e.g. `BANK=2`, `BANK=10`) followed by exactly 1024 words,
8 per line, separated by single spaces. Every word is written as 5 octal digits holding the 15-bit word
(parity bit excluded). A word that the program never assembles anything into is written as `@`.

### Correctness requirements
* The rope must be bit-exact with what the original assembler produced: correct instruction encoding
  (including the extracode/extended forms, quarter-code instructions, `INDEX`, implied-address codes),
  correct bank/address arithmetic (fixed-fixed vs switchable fixed, `SETLOC`, `BANK`, `BLOCK`, relative
  addressing), all constant/address pseudo-ops (`OCT`, `DEC`, `2DEC`, `ADRES`, `CADR`, `2CADR`/`2BCADR`,
  `GENADR`, `FCADR`, `ECADR`, `BBCON`, `REMADR`, `DNPTR`, `DNCHAN`, ...), equates (`=`, `EQUALS`, `=MINUS`,
  `ERASE`, `EBANK=`, `SBANK=`, `MEMORY`, `SETLOC`, `COUNT`), and the interpretive language (opcode
  packing two per word, store codes, operand address encoding, index modifiers, push-down usage).
* `BNKSUM` must emit the bank checksum ("bugger") word exactly as YUL did, so that each bank's checksum
  is valid; report each bank's checksum and words used.
* Both Comanche055 and Luminary099 must assemble without errors.

### Deliverables
Source code, an automated test suite (unit tests of the tokenizer/parser, every instruction and
pseudo-op encoder, interpretive packing, bank arithmetic, plus end-to-end assembly of both programs),
and a README describing the architecture and the AGC conventions you implemented.
