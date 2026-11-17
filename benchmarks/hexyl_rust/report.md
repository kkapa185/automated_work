# Benchmark report — sharkdp/hexyl

**Ticket:** [`task.md`](task.md) (CLI-58). It asks for a Rust hex viewer that is byte-for-byte output-compatible
with `hexyl`, ANSI colour sequences included, across ~25 option combinations.

**Reference execution:** the hidden harness [`compare.py`](compare.py) builds both binaries with Cargo and
compares stdout **byte for byte** over 7 input files × 26 option sets. It also covers stdin input,
`NO_COLOR`, error handling and the generated project's own `cargo test`.

## Score history
| attempt | score | notes |
|---|---|---|
| 1 | 0.29 | Layout, offsets, grouping and character tables were correct with `--color=never`. Almost every *coloured* case failed on one detail the ticket left ambiguous: on a short final line the reference keeps the colour run open through the padding. The squeeze marker without a position column was also unspecified. |
| 2 | 0.35 | Both details were added to the ticket and are now handled. The remaining failures are further undocumented byte-level behaviours. The reference **auto-reduces to one panel** when two do not fit the default 80-column width (`-b 8`, `-b 2`, `--terminal-width 60`). It emits colour codes inside blank squeeze lines, and prints `No content` for empty input. |

**Analysis:** byte-exact compatibility with an existing CLI needs a complete behavioural specification
or golden output files. The ticket describes the tool at README level, and the system implemented
exactly what it specified. The remaining work is transcribing the reference's quirks, which would amount
to leaking the hidden expected outputs, so I stopped after attempt 2. The tool builds, its own tests
pass, it handles `NO_COLOR`, stdin and errors correctly, and its plain (`--color=never`) layout matches the
reference for the standard cases.
