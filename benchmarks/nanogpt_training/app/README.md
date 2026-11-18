# nanogpt — character-level GPT training & sampling (PyTorch)

A small, readable pipeline: char tokenisation, a GPT-2-style model, a deterministic CPU training loop and sampling.
Only dependency for ML is `torch` (`pytest` for tests).

## Install / test
    pip install -r requirements.txt
    python -m pytest -q

## Usage
    ./nanogpt prepare --input data/input.txt --out data/shakespeare_char
    ./nanogpt train --data data/shakespeare_char --out out-shakespeare-char --max-iters 5000
    ./nanogpt train --data data/shakespeare_char --out out-shakespeare-char --max-iters 6000 --resume
    ./nanogpt sample --out out-shakespeare-char --start "ROMEO:" --num-samples 3 --max-new-tokens 300 --top-k 40 --seed 1

`prepare` writes `train.bin`/`val.bin` (little-endian uint16 ids; first 90% of text = train) and `meta.json`
(`vocab_size`, `itos`, `stoi`), and prints `vocab size: N`, `train has X tokens`, `val has Y tokens`.

`train` options: `--n-layer --n-head --n-embd --block-size --batch-size --max-iters --eval-interval --eval-iters
--learning-rate --min-lr --warmup-iters --lr-decay-iters --dropout --weight-decay --beta1 --beta2 --grad-clip --seed
--device --resume`. Defaults: 6 layers, 6 heads, 384 embd, block 256, batch 64, 5000 iters, eval every 250 with 200
batches, lr 1e-3 → 1e-4, warmup 100, lr-decay-iters = max-iters, dropout 0.2, wd 0.1, betas 0.9/0.99, clip 1.0,
seed 1337, device cpu. The defaults are not given by the spec and are assumptions;
the default model is large for CPU — use e.g. `--n-layer 4 --n-embd 128 --n-head 4 --block-size 64` for quick runs.
Output dir gets `ckpt.pt`, `metrics.json` and a copy of `meta.json`.
On `--resume`, unspecified options come from the checkpoint; model-shape options cannot be changed.

`sample` prints samples (including the start text) separated by `---------------`.
Defaults: start "\n", 1 sample, 500 tokens, temperature 0.8, seed 1337.

## Design
- `nanogpt_lib/data.py` tokeniser, bin I/O, random batch windows. `model.py` GPT (pre-LN, tied head, no biases,
  init N(0,0.02), residual projections 0.02/sqrt(2·n_layer)). `train.py` loop, LR schedule, eval, checkpointing.
  `sample.py`, `cli.py`.
- LR: iterations `i < warmup` use `lr·(i+1)/warmup`; then cosine to `min_lr` at `lr_decay_iters`, constant after.
- Weight decay only on parameters with ≥2 dims. `n_params` excludes position embeddings (tied head counted once).
- Determinism: one global torch seed; the checkpoint stores the RNG state, written right after each eval, so a
  resumed run reproduces the uninterrupted run exactly (given the same lr-decay-iters). Resume does not re-evaluate
  the checkpoint's iteration; `metrics.json` entries after the checkpoint are discarded and re-appended.
- Checkpoint and eval happen at iteration 0, every `eval-interval`, and `max-iters`.
