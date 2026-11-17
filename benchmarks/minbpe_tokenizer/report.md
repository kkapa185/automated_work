# Benchmark report — karpathy/minbpe

**Ticket:** [`task.md`](task.md) (NLP-48). It describes byte-level BPE, the `Basic`/`Regex` tokenizer API, the
merge tie-breaking rule and the `.model` file format.

**Reference execution:** the hidden harness [`compare.py`](compare.py) runs the same driver against the
reference package and the generated one:
- trains both tokenizers on the repo's own `tests/taylorswift.txt` with a vocabulary of 512;
- compares every learned merge, the token ids on 8 probes (empty, emoji, CJK, control characters, a
  4 kB excerpt), the round-trip, the saved `.model` bytes, `load()`, and special-token handling.

## Result (attempt 1, system `86683d9`): score 1.00 (16/16)
- All 256 merges match exactly, for both Basic and Regex.
- Every encoding and both `.model` files are byte-identical; `load()` reproduces the encodings.
- Special tokens work in `all`, `none` and the default raising mode.
- Speed: Regex training takes 0.2 s against the reference's 8.1 s, probably because it counts each
  distinct chunk once (I didn't read its code) — and it still reproduces every merge exactly.
  Basic takes 16 s against 4.6 s, within the 3x budget.

**Process:** 4 turns on one session (`221f9d0f…`): plan → implement → review (GAPS_FIXED) → review (PASS).
$1.07, about 5 minutes of model time.

**System observations:** nothing to fix. The ticket's precise tie-breaking rule was enough for
bit-exact merges.
