"""Training loop: AdamW, warmup + cosine LR, grad clipping, eval, checkpoint/resume."""
import json
import math
import os
import shutil

import torch

from .data import DataError, get_batch, load_meta, read_bin
from .model import GPT, GPTConfig

DEFAULTS = dict(n_layer=6, n_head=6, n_embd=384, block_size=256, batch_size=64, max_iters=5000,
                eval_interval=250, eval_iters=200, learning_rate=1e-3, min_lr=1e-4, warmup_iters=100,
                lr_decay_iters=None, dropout=0.2, weight_decay=0.1, beta1=0.9, beta2=0.99,
                grad_clip=1.0, seed=1337, device="cpu")
MODEL_KEYS = ("n_layer", "n_head", "n_embd", "block_size", "dropout")


def get_lr(it, learning_rate, min_lr, warmup_iters, lr_decay_iters):
    """Linear warmup, then cosine decay to min_lr at lr_decay_iters, constant after."""
    if it < warmup_iters:
        return learning_rate * (it + 1) / warmup_iters
    if it >= lr_decay_iters:
        return min_lr
    ratio = (it - warmup_iters) / max(1, lr_decay_iters - warmup_iters)
    coeff = 0.5 * (1.0 + math.cos(math.pi * ratio))
    return min_lr + coeff * (learning_rate - min_lr)


@torch.no_grad()
def estimate_loss(model, datasets, batch_size, block_size, eval_iters):
    model.eval()
    out = {}
    for split, data in datasets.items():
        losses = torch.zeros(eval_iters)
        for k in range(eval_iters):
            x, y = get_batch(data, batch_size, block_size)
            losses[k] = model(x.to(next(model.parameters()).device), y.to(next(model.parameters()).device))[1].item()
        out[split] = losses.mean().item()
    model.train()
    return out


def train(data_dir, out_dir, overrides, resume=False, log=print):
    """Run training. `overrides` maps option name -> value (None = unspecified)."""
    ckpt_path = os.path.join(out_dir, "ckpt.pt")
    metrics_path = os.path.join(out_dir, "metrics.json")
    ckpt = None
    if resume:
        if not os.path.exists(ckpt_path):
            raise DataError(f"cannot resume: {ckpt_path} not found")
        ckpt = torch.load(ckpt_path, map_location="cpu", weights_only=False)
    base = dict(DEFAULTS)
    if ckpt:
        base.update(ckpt["config"]["train"])
        base.update(ckpt["config"]["model"])
    cfg = dict(base)
    for k, v in overrides.items():
        if v is not None:
            if ckpt and k in MODEL_KEYS and v != base[k]:
                raise DataError(f"cannot change model option {k} when resuming")
            cfg[k] = v
    if ckpt and overrides.get("lr_decay_iters") is None and ckpt["config"]["train"].get("lr_decay_iters") is None:
        cfg["lr_decay_iters"] = None
    lr_decay_iters = cfg["lr_decay_iters"] if cfg["lr_decay_iters"] is not None else cfg["max_iters"]
    if cfg["n_embd"] % cfg["n_head"] != 0:
        raise DataError(f"n_embd ({cfg['n_embd']}) must be divisible by n_head ({cfg['n_head']})")
    if cfg["eval_interval"] < 1 or cfg["eval_iters"] < 1 or cfg["batch_size"] < 1:
        raise DataError("eval_interval, eval_iters and batch_size must be >= 1")

    meta, _, _ = load_meta(data_dir)
    datasets = {"train": read_bin(os.path.join(data_dir, "train.bin")),
                "val": read_bin(os.path.join(data_dir, "val.bin"))}
    for name, d in datasets.items():
        if len(d) <= cfg["block_size"]:
            raise DataError(f"{name} data has {len(d)} tokens; need more than block_size={cfg['block_size']}")
    device = cfg["device"]

    mcfg = GPTConfig(vocab_size=meta["vocab_size"], **{k: cfg[k] for k in MODEL_KEYS})
    torch.manual_seed(cfg["seed"])
    model = GPT(mcfg)
    opt = model.configure_optimizer(cfg["learning_rate"], cfg["weight_decay"], (cfg["beta1"], cfg["beta2"]))
    start = 0
    os.makedirs(out_dir, exist_ok=True)
    metrics = {"n_params": model.num_params(), "evals": []}
    if ckpt:
        model.load_state_dict(ckpt["model"])
        opt.load_state_dict(ckpt["optimizer"])
        start = ckpt["iter"]
        torch.set_rng_state(ckpt["rng_state"])
        if os.path.exists(metrics_path):
            with open(metrics_path) as f:
                metrics = json.load(f)
            metrics["evals"] = [e for e in metrics["evals"] if e["iter"] <= start]
            metrics["n_params"] = model.num_params()
    model.to(device)
    for state in opt.state.values():
        for k, v in state.items():
            if torch.is_tensor(v):
                state[k] = v.to(device)
    src_meta = os.path.join(data_dir, "meta.json")
    if os.path.abspath(src_meta) != os.path.abspath(os.path.join(out_dir, "meta.json")):
        shutil.copyfile(src_meta, os.path.join(out_dir, "meta.json"))
    log(f"number of parameters: {metrics['n_params']:,}")

    train_cfg = {k: cfg[k] for k in DEFAULTS if k not in MODEL_KEYS}
    train_cfg["lr_decay_iters"] = cfg["lr_decay_iters"]
    config = {"model": mcfg.to_dict(), "train": train_cfg}

    def evaluate_and_save(it):
        losses = estimate_loss(model, datasets, cfg["batch_size"], cfg["block_size"], cfg["eval_iters"])
        log(f"step {it}: train loss {losses['train']:.4f}, val loss {losses['val']:.4f}")
        metrics["evals"].append({"iter": it, "train_loss": losses["train"], "val_loss": losses["val"]})
        torch.save({"model": model.state_dict(), "optimizer": opt.state_dict(), "iter": it,
                    "config": config, "rng_state": torch.get_rng_state()}, ckpt_path)
        with open(metrics_path, "w") as f:
            json.dump(metrics, f, indent=2)

    if start >= cfg["max_iters"]:
        log(f"checkpoint already at iteration {start} >= max_iters {cfg['max_iters']}; nothing to do")
        with open(metrics_path, "w") as f:
            json.dump(metrics, f, indent=2)
        return metrics
    model.train()
    for it in range(start, cfg["max_iters"] + 1):
        if (it % cfg["eval_interval"] == 0 or it == cfg["max_iters"]) and not (ckpt and it == start):
            evaluate_and_save(it)
        if it == cfg["max_iters"]:
            break
        lr = get_lr(it, cfg["learning_rate"], cfg["min_lr"], cfg["warmup_iters"], lr_decay_iters)
        for g in opt.param_groups:
            g["lr"] = lr
        x, y = get_batch(datasets["train"], cfg["batch_size"], cfg["block_size"])
        _, loss = model(x.to(device), y.to(device))
        opt.zero_grad(set_to_none=True)
        loss.backward()
        if cfg["grad_clip"] and cfg["grad_clip"] > 0:
            torch.nn.utils.clip_grad_norm_(model.parameters(), cfg["grad_clip"])
        opt.step()
    return metrics
