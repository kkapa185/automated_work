# CLI-58: `hexyl` — a colourful command-line hex viewer in Rust

Write a Rust (stable, edition 2021) command-line tool named `hexyl` (Cargo binary target `hexyl`) that
prints a hex dump of a file or of stdin, with a bordered table layout and colour-coded byte categories.
It must be output-compatible (byte for byte, including ANSI colour sequences) with the well-known `hexyl`
tool for the options below, so existing scripts and screenshots stay valid.

## Default layout (16 bytes per line in two 8-byte panels)
```
┌────────┬─────────────────────────┬─────────────────────────┬────────┬────────┐
│00000000│ 48 65 6c 6c 6f 2c 20 57 ┊ 6f 72 6c 64 21 00 01 02 │Hello, W┊orld!⋄••│
│00000010│ ff 80 20 74 61 62 09 68 ┊ 65 72 65 0a             │×× tab_h┊ere_    │
└────────┴─────────────────────────┴─────────────────────────┴────────┴────────┘
```
(the example is for input bytes `Hello, World!\0\x01\x02\xff\x80 tab\there\n`, shown with `--color=never`).
* Position column: 8 lower-case hex digits of the offset (plus `--display-offset`).
* Byte categories and their character-panel glyphs / colours (SGR codes): NULL `⋄` bright black (`90`);
  printable ASCII as itself, cyan (`36`); ASCII whitespace green (`32`) — space as ` `, other whitespace
  as `_`; other ASCII (control) `•` green (`32`); non-ASCII `×` yellow (`33`). The position column is
  bright black. Colour runs are emitted only when the category changes and reset with `39` before each
  border character, e.g. `│\x1b[90m00000000\x1b[39m│ \x1b[36m48 65 6c 6c 6f 2c \x1b[32m20 \x1b[36m57\x1b[39m ┊ ...`.
  On a short final line the colour run stays open through the padding spaces and is reset just before
  the border, e.g. `\x1b[36m65 72 65 \x1b[32m0a            \x1b[39m │` (not `...0a\x1b[39m            │`).
* Squeezing: when a whole line repeats the previous line, print one line with `*` in the position column
  (padded, panels blank) and skip further identical lines; the final line shows the total length.
  When the position column is hidden (`-P`, `-p`), the `*` is printed as the first character of the
  first hex panel instead, e.g. with `--color=never -C -P --border ascii`:
  `|*                        |                         |        |        |`.
  `-v/--no-squeezing` disables it.

## Options
`-n/--length N` (also `-c`, `-l`, `--bytes`), `-s/--skip N` (negative = from end), `--block-size SIZE`;
N may be decimal, `0x` hex, or have units `kB MB GB` (1000) / `KiB MiB GiB` (1024) and `block`.
`-v/--no-squeezing`, `--color always|auto|never|force` (default `always`; `NO_COLOR` env disables unless
`force`), `--border unicode|ascii|none` (ASCII uses `+ - |` and `|` panel separator), `-p/--plain`
(= `--no-characters --no-position --border=none --color=never`), `--no-characters`, `-C/--characters`,
`--character-table default|ascii|braille` (ascii: `.` for every non-printable byte; braille: dot patterns
for non-printable bytes), `-P/--no-position`, `-o/--display-offset N`, `--panels N|auto` (auto = as many as
fit in the terminal width), `-g/--group-size 1|2|4|8` (bytes per group, groups separated by a space),
`--endianness little|big` (byte order inside a group), `-b/--base 2|8|10|16` (or `binary`, `octal`,
`decimal`, `hexadecimal`; widths 8/3/3/2 digits per byte), `--terminal-width N`, `-h`, `-V`.
Errors (missing file, invalid arguments) go to stderr with a non-zero exit code.

Deliverables: the Cargo project (`cargo build --release` must work offline-friendly with few, mainstream
dependencies such as `clap` and `anyhow`), integration tests (`cargo test`) and a README.
