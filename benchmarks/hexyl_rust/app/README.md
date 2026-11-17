# hexyl

A colourful command-line hex viewer written in Rust (edition 2021). It dumps a file or stdin as a
bordered table with colour-coded byte categories.

```
┌────────┬─────────────────────────┬─────────────────────────┬────────┬────────┐
│00000000│ 48 65 6c 6c 6f 2c 20 57 ┊ 6f 72 6c 64 21 00 01 02 │Hello, W┊orld!⋄••│
│00000010│ ff 80 20 74 61 62 09 68 ┊ 65 72 65 0a             │×× tab_h┊ere_    │
└────────┴─────────────────────────┴─────────────────────────┴────────┴────────┘
```

## Build, run, test
```
cargo build --release          # binary: target/release/hexyl
target/release/hexyl FILE      # or: cat FILE | hexyl
cargo test                     # integration + unit tests
```
Dependencies: `clap` (derive), `anyhow`, `terminal_size`; all build offline from a populated cargo cache.

## Options
`-n/-c/-l/--bytes N`, `-s/--skip N` (negative = from end), `--block-size SIZE`, `-v/--no-squeezing`,
`--color always|auto|never|force` (default `always`; `NO_COLOR` disables unless `force`),
`--border unicode|ascii|none`, `-p/--plain`, `--no-characters`, `-C/--characters`,
`--character-table default|ascii|braille`, `-P/--no-position`, `-o/--display-offset N`,
`--panels N|auto`, `--terminal-width N`, `-g/--group-size 1|2|4|8`, `--endianness little|big`,
`-b/--base 2|8|10|16|binary|octal|decimal|hexadecimal`, `-h`, `-V`.

Numbers: decimal, `0x` hex, units `kB MB GB` (1000), `KiB MiB GiB` (1024), `block` (`--block-size`, default 512).

Byte colours: NULL `⋄` bright black; printable ASCII cyan; whitespace green (`_`, space as blank);
other control `•` green; non-ASCII `×` yellow. The position column is bright black.

## Design
* `src/lib.rs` — `parse_size`, byte categories, `Printer` (header/footer, one generic line renderer
  driven by per-byte slots so padding, groups, endianness, bases and panel counts share one code path,
  and the squeezing state machine).
* `src/main.rs` — clap option parsing, input opening (seek for files; stdin is streamed, or buffered for a
  negative skip), skip/length handling, colour/NO_COLOR resolution.
* Displayed offsets start at `skip + display-offset`. Squeezing collapses repeated *full* lines into a `*` line;
  if the input ends while squeezing, a final line with the total length is shown. Empty input prints an empty
  table row. Border `none` renders border characters as spaces. Braille table maps non-printable bytes to
  U+2800+byte; the ascii table shows `.`.
