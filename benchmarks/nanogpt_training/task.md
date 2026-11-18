# ML-300: Character-level GPT training & sampling pipeline (PyTorch, nanoGPT-style)

Build a small, readable but complete pipeline to train and sample GPT language models, runnable as
`./nanogpt <command>` from the workspace root (Python + PyTorch; do not copy nanoGPT/minGPT/HF code;
`torch` is the only ML dependency). The tiny-Shakespeare corpus is in `data/input.txt`.

Commands:
* `./nanogpt prepare --input data/input.txt --out data/shakespeare_char` — character-level tokenisation:
  vocabulary = sorted set of all characters; first 90% of the text is train, the rest val; write
  `train.bin`/`val.bin` (uint16 token ids) and `meta.json` (`vocab_size`, `itos`, `stoi`); print
  `vocab size: N`, `train has X tokens`, `val has Y tokens` (thousands separated by commas).
* `./nanogpt train --data <dir> --out <dir> [options]` with options `--n-layer --n-head --n-embd
  --block-size --batch-size --max-iters --eval-interval --eval-iters --learning-rate --min-lr
  --warmup-iters --lr-decay-iters --dropout --weight-decay --beta1 --beta2 --grad-clip --seed --device
  --resume`. Model = GPT-2 architecture: token + learned position embeddings, `n_layer` pre-LayerNorm
  blocks (causal multi-head self-attention, 4x GELU MLP), final LayerNorm, LM head **tied** to the token
  embedding; LayerNorm/Linear **without biases**; init N(0, 0.02) with residual projections scaled by
  `0.02/sqrt(2*n_layer)`. AdamW (weight decay only on ≥2-D parameters, defaults beta1 0.9, beta2 0.99,
  weight decay 0.1), linear warmup then cosine decay to `min_lr`, gradient clipping 1.0, random
  `block_size` windows sampled from the token stream. At iteration 0 and every `eval_interval` (and at
  `max_iters`), estimate train/val loss as the mean over `eval_iters` random batches and print
  `step N: train loss A, val loss B`. Save `ckpt.pt` (model, optimizer, iteration, config) and append to
  `metrics.json`: `{"n_params": <parameters excluding position embeddings>, "evals": [{"iter", "train_loss",
  "val_loss"}]}`. `--resume` continues from the checkpoint to `max_iters`.
* `./nanogpt sample --out <dir> [--start TEXT] [--num-samples K] [--max-new-tokens N] [--temperature T]
  [--top-k K] [--seed S]` — autoregressive sampling, print the decoded samples separated by `---------------`.

Training must be deterministic for a fixed seed on CPU. Deliverables: code, tests (tokeniser round-trip,
shapes, causal masking, loss at init ≈ ln(vocab), overfitting a tiny batch, checkpoint/resume), README.
