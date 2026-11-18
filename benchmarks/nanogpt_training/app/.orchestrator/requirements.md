# Requirements: char-level GPT training & sampling pipeline

## Product
A small PyTorch CLI (`./nanogpt prepare|train|sample`) implementing character-level tokenisation, a GPT-2-style
model (tied embeddings, bias-free LN/Linear), a deterministic CPU training loop (AdamW, warmup+cosine LR, grad clip,
eval, checkpoint/resume, metrics.json) and autoregressive sampling. Small product: no milestones.

## Acceptance criteria
R1. `prepare --input F --out D`: vocab = sorted set of chars; first 90% of text (int(0.9*len)) train, rest val; writes
    `train.bin`, `val.bin` (uint16 little-endian ids) and `meta.json` (`vocab_size`, `itos`, `stoi`).
R2. prepare prints `vocab size: N`, `train has X tokens`, `val has Y tokens` with comma thousands separators.
R3. Tokeniser round-trip: decode(encode(s)) == s; meta.json itos/stoi consistent (itos keys are strings in JSON).
R4. Model: token + learned position embedding, n_layer pre-LN blocks (causal MHA, 4x GELU MLP), final LN, tied LM head;
    no biases in Linear/LayerNorm; logits shape (B,T,V) (full sequence) ; loss when targets given.
R5. Init N(0,0.02) for Linear/Embedding; residual projections (attn c_proj, mlp c_proj) std 0.02/sqrt(2*n_layer).
R6. Causal masking: changing future tokens does not change earlier logits.
R7. Loss at init ≈ ln(vocab_size).
R8. Overfit a tiny fixed batch to near-zero loss.
R9. AdamW: weight decay only on params with dim>=2; betas (beta1,beta2), defaults 0.9/0.99, wd 0.1.
R10. LR: linear warmup over warmup_iters, then cosine decay to min_lr at lr_decay_iters, min_lr after.
R11. Grad clipping at --grad-clip (default 1.0). Batches: random block_size windows (x, y shifted by 1) from train/val stream.
R12. Eval at iter 0, every eval_interval and at max_iters: mean over eval_iters random batches for train/val (model eval mode,
    no grad); prints `step N: train loss A, val loss B`.
R13. Saves `ckpt.pt` (model, optimizer, iter, config) and `metrics.json` {"n_params" (excluding position embeddings), "evals":[{iter,train_loss,val_loss}]}.
R14. `--resume` loads checkpoint, continues to max_iters, appends to metrics.json; resumed run reproduces the uninterrupted run
    (RNG state saved in checkpoint).
R15. Determinism: same seed on CPU => identical eval losses.
R16. CLI options: --n-layer --n-head --n-embd --block-size --batch-size --max-iters --eval-interval --eval-iters --learning-rate
    --min-lr --warmup-iters --lr-decay-iters --dropout --weight-decay --beta1 --beta2 --grad-clip --seed --device --resume.
R17. `sample --out D [--start --num-samples --max-new-tokens --temperature --top-k --seed]`: loads ckpt+meta, prints samples
    separated by `---------------`; deterministic for a seed; top-k restricts choices; context cropped to block_size.
R18. Errors: unknown chars in --start, missing ckpt, n_embd % n_head != 0 give a clear message and nonzero exit.
R19. README, requirements.txt, tests runnable via `python -m pytest`.

## Assumptions
- Defaults (not given): n_layer 6, n_head 6, n_embd 384, block 256, batch 64, max_iters 5000, eval_interval 250, eval_iters 200,
  lr 1e-3, min_lr 1e-4, warmup 100, lr_decay_iters = max_iters, dropout 0.2, seed 1337, device cpu (any torch device string via --device).
- Data dir for sample is read from the data dir recorded in the checkpoint config; falls back to meta.json copied into --out by train.
- `train` copies meta.json into out dir.
- Split uses int(0.9*n).
- Weight decay applies to ≥2-D params; tied weight counted once.
- n_params excludes position embeddings; tied head counted once.

## Test strategy
Unit tests (pytest) for R3-R11 with direct imports; CLI integration tests via subprocess for R1,R2,R12-R18 on a tiny synthetic corpus
and a tiny run; known-answer: prepare on "hello\n" style string with hand-computed vocab/ids; LR schedule hand-computed values.
