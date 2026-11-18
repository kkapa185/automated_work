"""Autoregressive sampling from a trained checkpoint."""
import os

import torch

from .data import DataError, decode, encode, load_meta
from .model import GPT, GPTConfig

SEPARATOR = "---------------"


def sample(out_dir, start="\n", num_samples=1, max_new_tokens=500, temperature=0.8, top_k=None,
           seed=1337, device="cpu"):
    ckpt_path = os.path.join(out_dir, "ckpt.pt")
    if not os.path.exists(ckpt_path):
        raise DataError(f"{ckpt_path} not found (run `train` first)")
    ckpt = torch.load(ckpt_path, map_location="cpu", weights_only=False)
    _, stoi, itos = load_meta(out_dir)
    model = GPT(GPTConfig(**ckpt["config"]["model"]))
    model.load_state_dict(ckpt["model"])
    model.to(device).eval()
    ids = encode(start, stoi)
    if not ids:
        raise DataError("--start must not be empty")
    torch.manual_seed(seed)
    outputs = []
    for _ in range(num_samples):
        idx = torch.tensor([ids], dtype=torch.long, device=device)
        out = model.generate(idx, max_new_tokens, temperature=temperature, top_k=top_k)
        outputs.append(decode(out[0].tolist(), itos))
    return outputs
