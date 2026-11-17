# agcasm — a Block II Apollo Guidance Computer assembler

`agcasm` assembles the Apollo 11 flight software (`agc_source/Comanche055`, the
Command Module "Colossus 2A", and `agc_source/Luminary099`, the Lunar Module
"Luminary 1A") into its fixed-memory *core rope* image.  It is a two-pass
assembler written in pure Python 3 (standard library only, Python >= 3.10).

## Usage

```
./agcasm assemble agc_source/Comanche055/MAIN.agc -o out/Comanche055.binsource \
        [--symbols out/Comanche055.symbols.json] [--listing out/Comanche055.lst] [-q]
```

* Exit status 0 on success; 1 with `file:line: message` diagnostics on stderr
  otherwise (no output files are written); 2 for a usage error.  Bad input never
  produces a traceback and several errors are reported in one run.
* On success a per-bank table (checksum word and words used) is printed.
* `make rope` assembles both programs into `out/`; `make test` runs the tests
  (`python3 -m unittest discover -s tests`).  No installation step is needed.

### Outputs

* **`.binsource`** – comment lines start with `;`; then for the 36 fixed banks in
  the order `2, 3, 0, 1, 4 … 43` (octal): `BANK=<octal>` followed by 128 lines of
  eight 5-digit octal words (the 15-bit word, parity excluded).  A word nothing
  was assembled into is `@`.
* **`--symbols`** – JSON `{name: {value, kind, bank, file, line}}`.  `kind` is
  `fixed`, `erasable` or `constant` (an `EQUALS` of a plain number).  `value` is
  the S-register address as printed in listings: `2000-3777` for a switchable
  bank (with `bank` its number), `4000-7777` for the fixed-fixed banks 2/3,
  `0-1777` for erasable (`bank` = E-bank for `1400-1777`, else `null`).
* **`--listing`** – `BB,AAAA  words  source` for every source line of every file.

## Architecture (`agclib/`)

| module | role |
| --- | --- |
| `lexer.py` | line tokenizer (label in column 1, `#` comments, far-right annotations, `+n` markers), recursive `$FILE.agc` include expansion (cycle safe, near-miss file names tolerated with a warning) |
| `model.py` | `Val` (number / erasable / fixed address), bank & address arithmetic (`saddr`, `cadr_of`, `fbank_of`, one's-complement helpers) |
| `numbers.py` | octal/decimal literals, `DEC`/`2DEC` conversion with `Bn`/`E` scaling |
| `expr.py` | operand expressions (`SYM +n`, relative `+n`, `,1`/`,2` index suffix) |
| `tables.py` | basic instruction table, interpretive op tables, pseudo-op set |
| `interp.py` | interpretive-language classification and operand encoding |
| `assembler.py` | pass 1 (location counter, symbols, allocation, interpretive operand look-ahead), deferred equates, pass 2 (encoding), BNKSUM |
| `output.py`, `cli.py` | rope / JSON / listing writers and the command line |

Data flow: `MAIN.agc` → include expansion → pass 1 allocates every word and
defines symbols → forward `EQUALS` resolved → pass 2 encodes words → bank
checksum words → writers.

## AGC conventions implemented

**Memory.**  Erasable addresses are linear `0-3777` (E0-E7; `1400-1777` is the
switchable window, S-address `1400 + (a & 377)`).  Fixed addresses are linear
`bank*2000 + offset`; banks 2/3 are fixed-fixed (`4000-7777`), others appear at
`2000-3777`.  A *CADR* is `FBANK<<10 | offset` (banks `40-43` alias FBANK
`30-33` and carry super-bank bits `0100` in `BBCON`/`2CADR` words); an *ECADR* is
the linear erasable address.

**Location control.**  `BANK n`/`BLOCK n` continue in bank *n* after the highest
word used so far; `SETLOC sym [+n]` jumps to a symbol's location (bank and
offset); a blank `BANK` then skips to the first free word (this is how the
"relative SETLOC" tags work); `SETLOC 4000` is fixed-fixed, numeric `SETLOC` in
erasable mode is an erasable address; `ERASE`, `ERASE +n` (n+1 words) and
`ERASE a - b`; `=`, `EQUALS` (blank = current location), `=MINUS`, `=PLUS`,
`EBANK=`, `SBANK=`, `COUNT`, `COUNT*`, `MEMORY` (accepted).  Overlapping
assembly, bank overflow and code in erasable memory are errors.

**Instructions.**  Quarter-code encodings (`TC 0`, `CCS/TCF 1`, `DAS/LXCH/INCR/ADS 2`,
`CA 3`, `CS 4`, `INDEX/DXCH/TS/XCH 5`, `AD 6`, `MASK 7`), extracodes (`READ…RXOR`,
`DV/BZF`, `MSU/QXCH/AUG/DIM`, `DCA`, `DCS`, `SU/BZMF`, `MP`) which must follow
`EXTEND` (it survives `INDEX` and directives), implied-address codes (`RETURN`,
`RELINT`, `INHINT`, `EXTEND`, `RESUME`, `XLQ`, `XXALQ`, `TCAA`, `OVSK`, `COM`,
`DOUBLE`, `DDOUBL`, `DCOM`, `ZL`, `ZQ`, `SQUARE`, `DTCB`, `DTCF`, `NOOP`).  The
double-precision operations `DAS/DXCH/DCA/DCS` encode the address of the
low-order word (operand + 1).  A leading `+n`/`-n` operand is relative to the
current location; numeric operands are added arithmetically to the opcode (so
`CAF 0 -1` is `27777`), and numeric addresses above `7777` are linear fixed
addresses.  Numeric opcodes (`7 SYM`) and `-OP` (complemented word) are supported.

**Constants.**  `OCT`, `DEC`, `DEC*`, `2DEC`, `2DEC*`, `2OCT`, `VN`, `MM`, `ADRES`,
`GENADR`, `REMADR`, `CADR`, `FCADR`, `ECADR`, `2CADR`, `BBCON`, `BBCON*`, `DNPTR`,
`DNCHAN`, `1DNADR…6DNADR`, and the `-` forms (one's complement of the word(s)).
`DEC` scaling: the value times `2**B`; a result below 1 is a fraction scaled to
the word (`2**14` / `2**28`), otherwise it is an integer.  Rounding is to
nearest; a fraction that rounds to full scale saturates.

**Interpretive language.**  Each operation has a 7-bit code *c* stored as *c+1*.
Two operations pack into one word, the first executed in bits 7-1, the second in
bits 14-8, and the word is stored complemented.  Classes: unary (`c = 8u`),
short shifts `SLn[R]`/`SRn[R]`/`VSLn`/`VSRn`, address-class operations (`c = 4n +
2*starred + 1`, operand word = address + 1, complemented for index register 2),
general shifts (`SL SR SLR SRR VSL VSR`, count biased by 200 with direction and
round bits), miscellaneous operations (`AXT,1` … `BOV`, raw operands; a branch
target is a CADR and a `+n` target is relative to the operand word itself), switch
operations (`SET`, `CLEAR`, `BON`, `BOFF`, … with the flag number `n` encoded as
word `n // 15`, bit `n % 15`), and store codes (`STORE`, `STORE,1/,2`, `STODL`,
`STOVL`, `STCALL`, starred forms; complemented after `STADR`).  Operand lines
follow the operation line; optional operands (push-up) are assigned by looking
ahead at how many operand lines follow.  A one-word data pseudo-op (`OCT 3`)
may stand in for an operand word.  `EXIT` returns to basic-language mode.

**BNKSUM.**  `BNKSUM n` reserves the last word of bank *n*; after assembly that
word is set so the one's-complement sum of the whole bank (unassembled words
count as 0) equals the bank number.  The per-bank checksum and words used are
printed after a successful run.

## Tolerance for the transcribed sources

The sources contain a few typographical errors that the original assembler
accepted.  They are handled explicitly and reported as warnings: include names
that differ from the file on disk (`LAMBERT_AIMPOINT_GUIDANCE.agc` for
`GENERAL_LAMBERT_AIMPOINT_GUIDANCE.agc`, `TRIM_GIMBAL_CNTROL_SYSTEM.agc`) and
symbol references one edit away from a unique defined symbol (`ZEROEROR` →
`ZEROERROR`, `GETLEWD` → `GETDLEWD`); this only applies once all symbols are
known, never to forward references.

## Testing

`tests/` contains unit tests for the tokenizer, number formats, every
instruction and pseudo-op, bank arithmetic, BNKSUM, interpretive packing and the
CLI, plus end-to-end assembly of both programs (rope format, 36 valid bank
checksums, symbol table, listing).  Run `python3 -m unittest discover -s tests`.

## Limitations

There is no reference listing in this workspace, so bit-exactness rests on the
conventions above; where the sources did not settle a convention (placement of
the BNKSUM word, double-precision operand adjustment, super-bank bits) the choice
is documented here and in `.orchestrator/requirements.md`.
