"""Character-level tokenisation, .bin I/O and random batch sampling."""
import json
import os
import sys
from array import array

import torch


class DataError(Exception):
    pass


def build_vocab(text):
    chars = sorted(set(text))
    stoi = {c: i for i, c in enumerate(chars)}
    itos = {i: c for i, c in enumerate(chars)}
    return stoi, itos


def encode(text, stoi):
    try:
        return [stoi[c] for c in text]
    except KeyError as e:
        raise DataError(f"character {e.args[0]!r} is not in the vocabulary") from None


def decode(ids, itos):
    return "".join(itos[int(i)] for i in ids)


def write_bin(path, ids):
    a = array("H", ids)
    if sys.byteorder == "big":
        a.byteswap()
    with open(path, "wb") as f:
        f.write(a.tobytes())


def read_bin(path):
    """Return a 1-D int64 tensor of the uint16 token ids stored in `path`."""
    with open(path, "rb") as f:
        raw = bytearray(f.read())
    if len(raw) % 2:
        raise DataError(f"{path}: size is not a multiple of 2 bytes")
    if not raw:
        return torch.zeros(0, dtype=torch.int64)
    t = torch.frombuffer(raw, dtype=torch.uint8).view(-1, 2).to(torch.int64)
    return t[:, 0] | (t[:, 1] << 8)  # little-endian uint16


def prepare(input_path, out_dir):
    """Tokenise `input_path` at character level; returns (vocab_size, n_train, n_val)."""
    with open(input_path, "r", encoding="utf-8", newline="") as f:
        text = f.read()
    if not text:
        raise DataError("input file is empty")
    stoi, itos = build_vocab(text)
    if len(stoi) > 65536:
        raise DataError("vocabulary does not fit in uint16")
    n = len(text)
    split = int(n * 0.9)
    train_ids = encode(text[:split], stoi)
    val_ids = encode(text[split:], stoi)
    os.makedirs(out_dir, exist_ok=True)
    write_bin(os.path.join(out_dir, "train.bin"), train_ids)
    write_bin(os.path.join(out_dir, "val.bin"), val_ids)
    with open(os.path.join(out_dir, "meta.json"), "w", encoding="utf-8") as f:
        json.dump({"vocab_size": len(stoi), "itos": {str(k): v for k, v in itos.items()}, "stoi": stoi},
                  f, ensure_ascii=False)
    return len(stoi), len(train_ids), len(val_ids)


def load_meta(directory):
    path = os.path.join(directory, "meta.json")
    if not os.path.exists(path):
        raise DataError(f"{path} not found (run `prepare` first)")
    with open(path, "r", encoding="utf-8") as f:
        meta = json.load(f)
    itos = {int(k): v for k, v in meta["itos"].items()}
    return meta, meta["stoi"], itos


def get_batch(data, batch_size, block_size):
    """Sample `batch_size` random windows; y is x shifted by one token."""
    ix = torch.randint(len(data) - block_size, (batch_size,))
    idx = ix[:, None] + torch.arange(block_size)[None, :]
    return data[idx], data[idx + 1]
