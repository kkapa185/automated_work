# AGC-42 requirements

## Product
`./agcasm`, a two-pass Block II Apollo Guidance Computer assembler written in Python 3 (stdlib only, no third-party deps).
It reads `MAIN.agc` and its `$FILE.agc` includes (Comanche055 and Luminary099, ~65k lines each), supports basic/extended
instructions, all pseudo-ops used by the sources and the interpretive language, and emits the 36-bank fixed-memory
rope image (`.binsource`), an optional symbol table (JSON) and an optional listing. BNKSUM emits YUL-style bank checksums.

## Acceptance criteria
R1. CLI `./agcasm assemble MAIN.agc -o OUT [--symbols F] [--listing F]` runs from the workspace root; creates output directories; exit 0 on success; non-zero otherwise. Unknown subcommand/missing file => usage/diagnostic, non-zero, no traceback.
R2. Diagnostics are `file:line: message` on stderr; bad input (unknown opcode, undefined symbol, duplicate label, bad operand, overflow of a bank, missing include, include loops, malformed numbers) never crashes with a traceback; assembly continues to report multiple errors; exit status 1.
R3. Tokenizer/parser: fixed free-form columns (label in col 1, opcode, operand, `#` comments), `$FILE.agc` include (recursive, cycle-safe, relative to the including file's directory), blank/remark lines, `-` prefixed opcode-less lines; labels may contain `+ - / * # ` characters used in the sources; operands with `+n`, `-n`, `,1`/`,2` index suffix, `*` (indirect/`NDX*`), `*-n` location-relative forms; `COUNT*`/`COUNT` accounting directives; `-` in label names (`-MAXADRS`, `S-7`) tokenised correctly.
R4. All basic instructions (TC, CCS, INDEX/NDX, XCH, CS, TS, AD, MASK, MP/DV/SU/BZF/BZMF extended, READ/WRITE/RAND/WAND/ROR/WOR/RXOR, DCA/DCS/DXCH/DAS/DDOUBL, LXCH/QXCH/ADS/INCR/AUG/DIM, CA/CAE/CAF, TCF, EXTEND, RESUME, RELINT/INHINT, XLQ/XXALQ/ZL/ZQ/RETURN/NOOP/OVSK/TCAA/DTCF/DTCB/COM/SQUARE/SQUARE/DOUBLE/DDOUBL/EDRUPT/BOTH/ROR...) encode bit-exactly, including extracode forms (EXTEND prefix check), quarter-code (BZF/BZMF/DV/SU/MP/QXCH/AUG/DIM/...), implied-address codes, erasable/fixed address range checks.
R5. Memory model: erasable banks E0-E7 (1400-1777 switchable), fixed-fixed banks 02/03 (4000-7777 address space 2000-3777 fixed), switchable fixed banks 00-43 (octal) incl. superbank (SBANK=) handling; BANK n, BLOCK n, SETLOC (absolute and symbolic), COUNT/COUNT*, `MEMORY`, `ERASE` (incl. ranges), `EQUALS`, `=`, `=MINUS`, `=PLUS`; erasable-bank tracking (EBANK=, ECADR, bbcon), fixed bank tracking for CADR/FCADR/2CADR/BBCON.
R6. Constants/address pseudo-ops: OCT, DEC (incl. B-scale, E-exponent, positive/negative, 1's-complement), 2DEC, 2DEC*, 2OCT, ADRES, CADR, FCADR, ECADR, 2CADR, 2BCADR, GENADR, BBCON, BBCON*, REMADR, DNPTR, DNCHAN, 1DNADR..6DNADR, 2FCADR, P/CHECKSUM-related ops, SBANK=, EBANK=, SUBRO, SETLOC, etc. — every pseudo-op that appears in either source file must be implemented; a unit test enumerates them.
R7. Interpretive language: interpreter opcodes (unary, binary, shift, store, branch, `RTB`, `CALL`, `GOTO`, `BON/BOF/SET/CLEAR/INVERT`, `STORE/STODL/STOVL/STCALL/STORE with push`), operand address encoding (erasable/fixed/ indexed `,1` `,2`, `*` forms, push-down `PUSH`, `D`-offset operands, `-n` complements), opcode packing two per word with the 7-bit opcode + parity rule and trailing half-word handling, `INTPRET` / `EXIT` mode switches, operand-less opcode pairs, store codes. Derived from the prose in INTERPRETER.agc and the sources' own usage.
R8. BNKSUM: emits the checksum word for the bank so that the YUL sum rule holds; stdout summary of each bank: checksum and words used/free.
R9. Rope output (`.binsource`): comment header `;`, 36 banks in order 02,03,00,01,04..43, each `BANK=<oct>` + 128 lines of 8 five-digit-octal words, unassembled words as `@`. Bank 02/03 hold addresses 4000-5777/6000-7777 (fixed-fixed); banks 00,01,04.. hold bank-relative 2000-3777.
R10. `--symbols` JSON `{name:{value,kind,bank,file,line}}` for every symbol; kind fixed|erasable|constant; fixed value = YUL-style address (switchable in 2000-3777 octal range as listed... see assumptions), erasable bank for erasable labels.
R11. `--listing` shows location, octal words, source text per line, for every included file.
R12. Both Comanche055 and Luminary099 assemble with zero errors and in reasonable time (<2 min each); no word is assembled twice (overlap is an error); output deterministic.
R13. Self-consistency checks implemented as tests: each BNKSUM bank checksum validates; every symbol referenced resolves; bank-relative addresses within a bank fall in 2000-3777 (switchable) / 4000-7777 (fixed-fixed); the `CHECKSUM` sums are verified by an independent reader in the tests.
R14. Test suite (`python3 -m unittest discover tests`) with: tokenizer/parser units, per-instruction encoding, per-pseudo-op, interpretive packing, bank arithmetic, diagnostics/no-crash, CLI, end-to-end of both programs. README documents architecture and AGC conventions.

## Assumptions
- Language: Python 3.13 stdlib only; `agcasm` is an executable launcher script; no external dependency manifest needed (a minimal `pyproject.toml` / Makefile with `test` target is shipped).
- With no reference listings permitted, correctness is derived from AGC architecture knowledge and the sources' own comments (e.g. INTERPRETER.agc, ASSEMBLY_AND_OPERATION_INFORMATION.agc) and consistency invariants (bank checksums, operand ranges, TC/TCF targets agree with labels).
- Symbols file: fixed-memory switchable-bank labels reported as address 2000-3777 octal + 02000 offset? Decision: switchable-fixed labels reported in 4000-7777 (YUL listing form, bank-relative) with `bank` = fixed bank; fixed-fixed labels as 4000-7777 with bank 2 or 3. Erasable: value = erasable address 0000-1777 with bank = E-bank for 1400-1777 else null.
- `@` for untouched words; BNKSUM occupies the bank's last word (not necessarily 1777 — placed at current location per source) and the checksum is chosen so that the 1's complement sum of the bank equals the bank number per YUL (sum==+bank, incl. bank-checksum-word).
- Ambiguous YUL details are recorded here as they are discovered during implementation.

## Test strategy
Unit (tests/test_*.py): tokenizer (R3), instruction encoder tables (R4), pseudo-ops (R6), interpretive packing (R7), bank arithmetic (R5), diagnostics (R2). Integration: tiny assembled snippets via the library to full rope; CLI tests via subprocess (R1, R9–R11). End-to-end: assemble both programs, validate format, 36x1024 words, checksum invariants, symbol sanity (R8, R12, R13).


## Implementation notes (Phase 2 decisions)
- Package is `agclib/` (the executable `./agcasm` lives at the workspace root).
- Symbol `value`: S-register address (switchable fixed 2000-3777, fixed-fixed 4000-7777, erasable 0-1777); `bank` = fixed bank / E-bank.
- BNKSUM word is the last word (offset 1777) of the bank; sum of bank (unassembled = 0) equals the bank number.
- Interpretive encoding derived from INTERPRETER.agc dispatch tables (see README).
- DAS/DXCH/DCA/DCS address the low-order word (+1); DTCB=52006, DTCF=52005, DDOUBL=20001, DCOM=40001.
- Typos in sources tolerated with warnings: near-miss include names, unique one-edit symbol references.
- Superbank bits 0o100 in BBCON/2CADR for banks 40-43; SBANK= is accepted and recorded.
