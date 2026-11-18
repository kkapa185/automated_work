import json
import os

from conftest import run_cli
from nanogpt_lib.data import build_vocab, decode, encode, get_batch, read_bin
import torch


def test_R1_R2_prepare_known_answer(tmp_path):
    # "abca\nab" has 7 chars; sorted vocab: '\n','a','b','c' -> 0..3; split int(0.9*7)=6
    (tmp_path / "t.txt").write_text("abca\nab")
    r = run_cli("prepare", "--input", tmp_path / "t.txt", "--out", tmp_path / "o")
    assert r.stdout.splitlines() == ["vocab size: 4", "train has 6 tokens", "val has 1 tokens"]
    assert (tmp_path / "o" / "train.bin").read_bytes() == bytes([1, 0, 2, 0, 3, 0, 1, 0, 0, 0, 1, 0])
    assert (tmp_path / "o" / "val.bin").read_bytes() == bytes([2, 0])
    meta = json.loads((tmp_path / "o" / "meta.json").read_text())
    assert meta["vocab_size"] == 4
    assert meta["stoi"] == {"\n": 0, "a": 1, "b": 2, "c": 3}
    assert meta["itos"] == {"0": "\n", "1": "a", "2": "b", "3": "c"}


def test_R2_thousands_separators(tmp_path):
    (tmp_path / "t.txt").write_text("ab" * 5000)
    r = run_cli("prepare", "--input", tmp_path / "t.txt", "--out", tmp_path / "o")
    assert "train has 9,000 tokens" in r.stdout and "val has 1,000 tokens" in r.stdout


def test_R3_roundtrip_unicode():
    s = "héllo wörld ✓\n\tend"
    stoi, itos = build_vocab(s)
    assert list(stoi) == sorted(set(s))
    assert decode(encode(s, stoi), itos) == s


def test_R1_bin_roundtrip_large_ids(tmp_path):
    from nanogpt_lib.data import write_bin
    write_bin(tmp_path / "x.bin", [0, 255, 256, 65535])
    assert read_bin(tmp_path / "x.bin").tolist() == [0, 255, 256, 65535]


def test_R11_batches_are_shifted_windows():
    data = torch.arange(100)
    x, y = get_batch(data, 8, 10)
    assert x.shape == y.shape == (8, 10)
    assert torch.equal(y, x + 1)
    assert x.max() + 1 <= 99


def test_R18_unknown_char_in_start(prepared, tmp_path):
    run_cli("train", "--data", prepared, "--out", tmp_path, "--max-iters", 2, "--eval-interval", 2,
            "--n-layer", 1, "--n-head", 1, "--n-embd", 8, "--block-size", 8, "--batch-size", 2, "--eval-iters", 1)
    r = run_cli("sample", "--out", tmp_path, "--start", "Z#", check=False)
    assert r.returncode != 0 and "not in the vocabulary" in r.stderr
