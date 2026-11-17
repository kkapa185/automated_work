# hexyl (CLI-58) requirements

## Product
`hexyl`: a Rust (stable, 2021) CLI that hex-dumps a file or stdin as a bordered table with a position column,
N panels of hex bytes and N panels of character glyphs, with ANSI colour per byte category, line squeezing,
multiple bases, grouping/endianness and several border/character styles. Output is byte-exact with the ticket.
Classification: CLI tool; single binary crate, deps `clap` (derive) + `anyhow` (+ std only otherwise; terminal width via
`--terminal-width` or `COLUMNS`/ioctl fallback to 80 without extra crates if possible).

## Acceptance criteria
R1  Default layout: 16 bytes/line, 2 panels of 8; header/footer/rows exactly as the ticket example
    (`--color=never`, input `Hello, World!\0\x01\x02\xff\x80 tab\there\n`). Position = 8 lowercase hex digits (+display offset).
R2  Categories: NULL `⋄` (SGR 90); printable ASCII 0x21..0x7e itself (36); ASCII whitespace (space,\t,\n,\v? ,\f,\r) green 32, space shown ` `, others `_`;
    other ASCII (control, 0x7f) `•` green 32; non-ASCII `×` yellow 33. Position column colour 90.
R3  Colour: run only emitted on category change; `\x1b[39m` reset before each border char (`│`/`┊`) when a colour is open; at line start
    colours restart. Example: `│\x1b[90m00000000\x1b[39m│ \x1b[36m48 65 6c 6c 6f 2c \x1b[32m20 \x1b[36m57\x1b[39m ┊ ...`.
    Short last line: colour run stays open through padding, reset just before border (`\x1b[36m65 72 65 \x1b[32m0a            \x1b[39m │`).
    Character panel likewise: colour open per category, reset before border; padding spaces in char panel are uncoloured/after reset.
R4  Squeezing: a full line identical to the previous line -> one `*` line (position col `*` padded to 8, panels blank), further
    identical lines skipped; last line then printed normally showing its offset; if the dump ends in squeezed lines, final line shows total length
    as position. With `-P`/`-p`, `*` is the first char of the first hex panel (ticket example
    `|*                        |                         |        |        |` with `--color=never -C -P --border ascii`).
    `-v/--no-squeezing` disables.
R5  Options `-n/--length` (`-c`,`-l`,`--bytes`), `-s/--skip` (negative = from end, requires seekable/ buffered input), `--block-size`;
    numbers: decimal, `0x` hex, units kB MB GB (1000), KiB MiB GiB (1024), `block` (multiplies by block size; default 512).
R6  `--color always|auto|never|force` (default always); `NO_COLOR` env (non-empty) disables unless `force`; `auto` = colour only if stdout is a tty.
R7  `--border unicode|ascii|none`; ASCII uses `+ - |` with `|` as panel separator; none omits border lines and border chars (columns still separated by spaces).
R8  `-p/--plain` = `--no-characters --no-position --border=none --color=never`; `--no-characters`; `-C/--characters` re-enables; `-P/--no-position`.
R9  `--character-table default|ascii|braille`; ascii: `.` for every non-printable byte (null, ws, control, non-ascii; space stays ` ` ... assumption: only printable ASCII 0x20..0x7e shown, others `.`);
    braille: non-printable bytes map to Braille patterns (U+2800 + byte value dot pattern).
R10 `-o/--display-offset N` shifts position column. `--panels N|auto`; auto = as many as fit in terminal width (`--terminal-width N` override).
R11 `-g/--group-size 1|2|4|8`, groups separated by an extra space; `--endianness little|big` reverses byte order inside a group when little... (big = natural order, default big).
R12 `-b/--base 2|8|10|16` or names; digits per byte 8/3/3/2 (octal/decimal zero-padded, `0o`-less).
R13 `-h`, `-V` work. Errors (missing file, invalid args) -> stderr, non-zero exit. Empty input prints header/empty-body/footer.
R14 Input from file arg or stdin (`-` or none). Output to stdout; broken pipe handled quietly.
R15 README, integration tests (`cargo test`), builds with `cargo build --release`.

## Assumptions
- Short last line pads hex panel with spaces and char panel with spaces; panels beyond data are blank-padded.
- Whitespace set = Rust `is_ascii_whitespace` (no 0x0b).
- With -P and border ascii/unicode the first column is omitted from the header/rows entirely.
- Group separator inside hex panel is one extra space; endianness little reverses bytes within each full group.
- Default block size 512; terminal width default 80 if unknown.

## Test strategy
Integration tests (assert_cmd-free: std::process::Command on `CARGO_BIN_EXE_hexyl`) with hand-derived expected strings for every ticket
example (R1-R4), plus option-level tests (R5-R13), error tests, stdin tests. Unit tests for number parsing.
- Empty input prints header, one blank row, footer. Skip adds to displayed offsets. Negative skip beyond start is an error.
