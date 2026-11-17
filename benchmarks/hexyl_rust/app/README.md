# hexyl

A colourful command-line hex viewer written in Rust (stable, edition 2021). It prints a bordered table with a
position column, hex panels and character panels, colour-coded by byte category.

```
┌────────┬─────────────────────────┬─────────────────────────┬────────┬────────┐
│00000000│ 48 65 6c 6c 6f 2c 20 57 ┊ 6f 72 6c 64 21 00 01 02 │Hello, W┊orld!⋄••│
│00000010│ ff 80 20 74 61 62 09 68 ┊ 65 72 65 0a             │×× tab_h┊ere_    │
└────────┴─────────────────────────┴─────────────────────────┴────────┴────────┘
```

## Build, run, test
```
cargo build --release          # binary: target/release/hexyl
target/release/hexyl FILE      # or: cat FILE | target/release/hexyl
cargo test                     # unit + integration tests
```
Dependencies: `clap`, `anyhow`, `libc` (terminal width ioctl). Everything builds offline once the crates are cached.

## Options
`-n/--length N` (`-c`, `-l`, `--bytes`), `-s/--skip N` (negative = from end), `--block-size SIZE` (default 512);
numbers: decimal, `0x` hex, units `kB MB GB` (1000), `KiB MiB GiB` (1024), `block`.
`-v/--no-squeezing`, `--color always|auto|never|force` (default `always`; `NO_COLOR` disables except for `force`),
`--border unicode|ascii|none`, `-p/--plain`, `--no-characters`, `-C/--characters`,
`--character-table default|ascii|braille`, `-P/--no-position`, `-o/--display-offset N`, `--panels N|auto`
(default 2), `-g/--group-size 1|2|4|8`, `--endianness little|big`, `-b/--base 2|8|10|16|binary|octal|decimal|hexadecimal`,
`--terminal-width N`, `-h`, `-V`. Errors go to stderr with a non-zero exit code.

## Design
- `src/size.rs` – number/unit parsing. `src/cli.rs` – clap definition and resolution of option interactions
  (`-p` defaults, colour decision, `--panels auto`) into a `Config`. `src/render.rs` – the table renderer.
  `src/main.rs` – input handling (file seek / stdin buffering for negative skips, `--length`) and error reporting.
- Colour is a small state machine: a run is emitted only when the byte category changes, and is reset (`ESC[39m`)
  just before a border character, so padding on short lines stays inside the open run.
- Squeezing compares full lines; the first repeat prints a `*` row, later repeats are skipped, and if the dump ends
  inside a squeezed region a final row shows the total offset.

## Assumptions
- ASCII whitespace = space, `\t`, `\n`, `\x0c`, `\r` (Rust `is_ascii_whitespace`); other control bytes and DEL are `•`.
- `ascii` table: printable ASCII 0x20–0x7e as-is, everything else `.`; `braille` table: everything else is U+2800+byte.
- `--border none` replaces border characters with spaces and omits the header/footer. Empty input prints one blank row.
- With `--skip`, the displayed offsets include the skipped bytes (plus `--display-offset`).
- Little endianness reverses byte order within each group (colours follow the bytes).
- `NO_COLOR` counts when non-empty. `-p` forces colour off unless `--color=force`.
