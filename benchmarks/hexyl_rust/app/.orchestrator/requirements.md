# hexyl clone — requirements

## Product
A Rust (edition 2021) CLI `hexyl` that hexdumps a file or stdin with a bordered table layout and
colour-coded byte categories, byte-for-byte output-compatible (including ANSI SGR sequences) with the
well-known hexyl for the listed options. Deps: clap (derive), anyhow, terminal_size (all in local cargo cache; offline build).

## Acceptance criteria
R1 Default layout: 16 bytes/line, 2 panels of 8, header/footer borders with unicode box chars, position col 8 lowercase hex digits, `┊` panel separator.
R2 Byte categories: NULL `⋄` (90), printable ASCII itself (36), whitespace green(32) space=' ' other `_`, other ASCII control `•` (32), non-ASCII `×` (33); position column 90.
R3 Colour runs emitted only on category change; reset `39` before each border char; exact sequences as in spec.
R4 Partial last line: hex area padded with spaces, character panel padded; footer unchanged.
R5 Squeezing: identical full lines collapse into one `*` line (padded), further identical lines skipped; final line shows total length offset; `-v` disables.
R6 `-n/-c/-l/--bytes N`; `-s/--skip N` (negative = from end of file; for stdin error if unseekable-handled by buffering); `--block-size`; numbers decimal, 0x hex, units kB MB GB / KiB MiB GiB, and `block` multiplier.
R7 `--color always|auto|never|force` default always; NO_COLOR disables unless force; auto = only if stdout is tty.
R8 `--border unicode|ascii|none`; ascii uses `+ - |` and `|` separator.
R9 `-p/--plain` = no-characters, no-position, border none, color never.
R10 `--no-characters`, `-C/--characters`; `--character-table default|ascii|braille`.
R11 `-P/--no-position`; `-o/--display-offset N`.
R12 `--panels N|auto` (auto fits terminal width), `--terminal-width N`.
R13 `-g/--group-size 1|2|4|8`, `--endianness little|big`.
R14 `-b/--base 2|8|10|16|binary|octal|decimal|hexadecimal` with 8/3/3/2 digits.
R15 Errors (missing file, bad args) to stderr, non-zero exit. `-h`, `-V` work.
R16 Empty input prints header, one blank row (empty position column and panels), and footer.
R17 `-` / no file = stdin.

## Assumptions
- Reference behaviours recalled from the spec only (no reference source consulted).
- Squeeze with offset-limited input: last line prints position of end; if the final line is itself squeezed, print `*` then final-length line.
- Position-less/no-border modes keep a leading space before bytes only when borders exist (none: no leading space... see tests).
- Empty input: header + footer rendered with 1 empty-ish panel layout; position column shown.

## Test strategy
Integration tests (assert_cmd-free; use std::process::Command with CARGO_BIN_EXE_hexyl) for R1–R17 with exact-string comparisons; unit tests for number parsing.
