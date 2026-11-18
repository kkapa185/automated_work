import json
import re

import torch

from conftest import TINY, run_cli

STEP = re.compile(r"^step (\d+): train loss ([\d.]+), val loss ([\d.]+)$", re.M)


def train(prepared, out, iters, *extra, check=True):
    return run_cli("train", "--data", prepared, "--out", out, "--max-iters", iters, *TINY, *extra, check=check)


def test_R12_R13_R15_train_outputs_and_determinism(prepared, tmp_path):
    a = train(prepared, tmp_path / "a", 10, "--seed", 3)
    b = train(prepared, tmp_path / "b", 10, "--seed", 3)
    steps = STEP.findall(a.stdout)
    assert [int(s[0]) for s in steps] == [0, 5, 10]
    assert STEP.findall(b.stdout) == steps
    m = json.loads((tmp_path / "a" / "metrics.json").read_text())
    assert [e["iter"] for e in m["evals"]] == [0, 5, 10]
    d = 16
    vocab = json.loads((prepared / "meta.json").read_text())["vocab_size"]
    assert m["n_params"] == vocab * d + 2 * (2 * d + 12 * d * d) + d
    ck = torch.load(tmp_path / "a" / "ckpt.pt", weights_only=False)
    assert {"model", "optimizer", "iter", "config"} <= set(ck) and ck["iter"] == 10
    # initial loss near ln(vocab)
    import math
    assert abs(m["evals"][0]["train_loss"] - math.log(vocab)) < 0.3
    c = train(prepared, tmp_path / "c", 10, "--seed", 4)
    assert STEP.findall(c.stdout) != steps


def test_R14_resume_matches_uninterrupted(prepared, tmp_path):
    full = train(prepared, tmp_path / "full", 15, "--seed", 7, "--lr-decay-iters", 15)
    train(prepared, tmp_path / "res", 5, "--seed", 7, "--lr-decay-iters", 15)
    r = run_cli("train", "--data", prepared, "--out", tmp_path / "res", "--max-iters", 15, "--resume")
    full_steps = STEP.findall(full.stdout)
    assert STEP.findall(r.stdout) == full_steps[2:]  # resumes after the iter-5 eval
    mf = json.loads((tmp_path / "full" / "metrics.json").read_text())
    mr = json.loads((tmp_path / "res" / "metrics.json").read_text())
    assert mf == mr
    assert torch.load(tmp_path / "res" / "ckpt.pt", weights_only=False)["iter"] == 15


def test_R14_resume_errors(prepared, tmp_path):
    r = run_cli("train", "--data", prepared, "--out", tmp_path / "none", "--resume", check=False)
    assert r.returncode != 0 and "ckpt.pt" in r.stderr
    train(prepared, tmp_path / "x", 5)
    r = run_cli("train", "--data", prepared, "--out", tmp_path / "x", "--resume", "--n-layer", 3, check=False)
    assert r.returncode != 0


def test_R18_bad_head_count(prepared, tmp_path):
    r = run_cli("train", "--data", prepared, "--out", tmp_path, "--n-embd", 10, "--n-head", 4, check=False)
    assert r.returncode != 0 and "divisible" in r.stderr


def test_R18_block_size_too_large(prepared, tmp_path):
    r = run_cli("train", "--data", prepared, "--out", tmp_path, "--block-size", 100000, check=False)
    assert r.returncode != 0


def test_R17_sample(prepared, tmp_path):
    train(prepared, tmp_path, 5)
    args = ["sample", "--out", tmp_path, "--start", "To be", "--num-samples", 3, "--max-new-tokens", 20,
            "--top-k", 5, "--seed", 1]
    r = run_cli(*args)
    parts = r.stdout.rstrip("\n").split("\n---------------\n")
    assert len(parts) == 3
    assert all(p.startswith("To be") and len(p) == 25 for p in parts)
    assert run_cli(*args).stdout == r.stdout
    assert run_cli(*[a if a != 1 else 2 for a in args]).stdout != r.stdout


def test_R17_sample_missing_ckpt(tmp_path):
    r = run_cli("sample", "--out", tmp_path, check=False)
    assert r.returncode != 0 and "ckpt.pt" in r.stderr


def test_R16_all_options_accepted(prepared, tmp_path):
    train(prepared, tmp_path, 3, "--learning-rate", "1e-3", "--min-lr", "1e-4", "--lr-decay-iters", 3,
          "--weight-decay", "0.1", "--beta1", "0.9", "--beta2", "0.95", "--grad-clip", "1.0", "--device", "cpu")


def test_R12_final_eval_at_max_iters_not_multiple(prepared, tmp_path):
    r = train(prepared, tmp_path, 7)  # eval-interval 5 -> evals at 0, 5, 7
    assert [int(s[0]) for s in STEP.findall(r.stdout)] == [0, 5, 7]
    assert [e["iter"] for e in json.loads((tmp_path / "metrics.json").read_text())["evals"]] == [0, 5, 7]
