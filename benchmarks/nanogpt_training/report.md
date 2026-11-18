# Benchmark report — karpathy/nanoGPT

**Ticket:** [`task.md`](task.md) (ML-300). It asks for a character-level GPT pipeline with `prepare`, `train`
(GPT-2 architecture, tied embeddings, no biases, AdamW, warmup and cosine schedule, eval/checkpoint/resume)
and `sample`, in PyTorch, written from scratch. The tiny-Shakespeare corpus was provided.

**Reference execution:** the hidden harness [`compare.py`](compare.py) runs the repo's own
`data/shakespeare_char/prepare.py` and `train.py` with a tiny CPU configuration: 2 layers, 2 heads,
64-dim embeddings, block 64, batch 12, 300 iterations, evals every 100. It runs the generated pipeline
with the same settings and compares:
- the prepare output and token counts;
- the exact parameter count;
- the validation-loss trajectory;
- determinism;
- resume from a checkpoint;
- sampling.

## Result (attempt 1): **score 1.00 (13/13)**
| | reference nanoGPT | generated |
|---|---|---|
| vocab / train tokens / val tokens | 65 / 1,003,854 / 111,540 | identical |
| parameters (excluding position embeddings) | 102,784 | **102,784** |
| val loss @0 / @100 / @200 / @300 | 4.180 / 2.590 / 2.446 / 2.396 | 4.180 / 2.705 / 2.581 / 2.516 |

All values are within the 5%/10% tolerances; the exact values differ because the batch sampling RNG
differs. Training is deterministic for a fixed seed. Resuming from a 150-iteration checkpoint reaches a
comparable loss at iteration 300. Sampling produces Shakespeare-like text.

**Process:** 4 turns on one session. $0.52.

**Harness notes:**
- The harness is self-checked with a stand-in adapter that maps the ticket's CLI onto nanoGPT's own
  scripts.
- The sample check allows status lines: at least 95% of the output characters must come from the
  vocabulary, because the reference `sample.py` itself prints `number of parameters` and `Loading meta`.
