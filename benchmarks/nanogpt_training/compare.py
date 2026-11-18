"""Run reference nanoGPT (data prep + train.py) and the generated ./nanogpt with the same tiny CPU config."""
import argparse
import json
import re
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from common import check, finish, run  # noqa: E402

DATA = "/home/user/bench_state/datasets/shakespeare/input.txt"
CFG = dict(n_layer=2, n_head=2, n_embd=64, block_size=64, batch_size=12, max_iters=300, eval_interval=100, eval_iters=20,
           learning_rate=1e-3, min_lr=1e-4, warmup_iters=20, lr_decay_iters=300, dropout=0.0)
CACHE = Path("/home/user/bench_state/nanogpt_reference.json")


def reference(ref: Path):
    if CACHE.exists():
        return json.loads(CACHE.read_text())
    d = Path("/home/user/bench_state/nanogpt_ref")
    if d.exists():
        shutil.rmtree(d)
    (d / "data" / "shakespeare_char").mkdir(parents=True)
    for f in ("train.py", "model.py", "configurator.py", "sample.py"):
        shutil.copy2(ref / f, d / f)
    shutil.copy2(ref / "data" / "shakespeare_char" / "prepare.py", d / "data" / "shakespeare_char")
    shutil.copy2(DATA, d / "data" / "shakespeare_char" / "input.txt")
    p = run([sys.executable, "prepare.py"], cwd=d / "data" / "shakespeare_char", timeout=600)
    args = [f"--{k}={v}" for k, v in CFG.items()] + ["--dataset=shakespeare_char", "--device=cpu", "--compile=False", "--log_interval=50",
                                                     "--out_dir=out", "--wandb_log=False", "--always_save_checkpoint=True"]
    t = run([sys.executable, "train.py", *args], cwd=d, timeout=7200)
    out = t.stdout + t.stderr
    res = {"prepare": p.stdout, "n_params": None, "evals": []}
    m = re.search(r"number of parameters: ([\d.]+)M", out)
    res["n_params_m"] = float(m.group(1)) if m else None
    import torch  # exact count from the reference model definition
    sys.path.insert(0, str(d))
    from model import GPT, GPTConfig  # noqa: E402
    model = GPT(GPTConfig(n_layer=2, n_head=2, n_embd=64, block_size=64, vocab_size=65, dropout=0.0, bias=False))
    res["n_params"] = model.get_num_params()
    res["evals"] = [{"iter": int(a), "train_loss": float(b), "val_loss": float(c)}
                    for a, b, c in re.findall(r"step (\d+): train loss ([\d.]+), val loss ([\d.]+)", out)]
    CACHE.write_text(json.dumps(res, indent=2))
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", required=True)
    ap.add_argument("--reference", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    app, ref = Path(a.app).resolve(), Path(a.reference)
    r = reference(ref)
    checks = []
    work = app / "_bench"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir()
    shutil.copy2(DATA, work / "input.txt")
    p = run([str(app / "nanogpt"), "prepare", "--input", str(work / "input.txt"), "--out", str(work / "data")], cwd=app, timeout=600)
    checks.append(check("prepare prints identical vocab and token counts", p.stdout.strip().splitlines()[-3:] == r["prepare"].strip().splitlines()[-3:],
                        f"{p.stdout[-200:]!r} vs {r['prepare'][-200:]!r} {p.stderr[-200:]}"))
    meta = work / "data" / "meta.json"
    checks.append(check("meta.json with vocab_size 65", meta.exists() and json.loads(meta.read_text()).get("vocab_size") == 65))
    tb = work / "data" / "train.bin"
    checks.append(check("train.bin holds 1,003,854 uint16 tokens", tb.exists() and tb.stat().st_size == 2 * 1003854, tb.stat().st_size if tb.exists() else None))
    opts = []
    for k, v in CFG.items():
        opts += [f"--{k.replace('_', '-')}", str(v)]
    t = run([str(app / "nanogpt"), "train", "--data", str(work / "data"), "--out", str(work / "out"), *opts, "--seed", "1337", "--device", "cpu"],
            cwd=app, timeout=7200)
    mpath = work / "out" / "metrics.json"
    m = json.loads(mpath.read_text()) if mpath.exists() else {}
    checks.append(check("train completes and writes metrics.json", t.returncode == 0 and bool(m), t.stderr[-400:]))
    checks.append(check(f"parameter count identical to reference GPT ({r['n_params']})", m.get("n_params") == r["n_params"], m.get("n_params")))
    ev = m.get("evals", [])
    gi = {e["iter"]: e for e in ev}
    for e in r["evals"]:
        g = gi.get(e["iter"])
        tol = 0.05 if e["iter"] == 0 else 0.10
        ok = g is not None and abs(g["val_loss"] - e["val_loss"]) <= tol * e["val_loss"]
        checks.append(check(f"val loss at iter {e['iter']} within {int(tol*100)}% of reference ({e['val_loss']:.3f})", ok, g))
    printed = re.findall(r"step (\d+): train loss ([\d.]+), val loss ([\d.]+)", t.stdout)
    checks.append(check("prints `step N: train loss A, val loss B` lines", len(printed) >= len(r["evals"]), printed[:2]))
    # determinism
    t2 = run([str(app / "nanogpt"), "train", "--data", str(work / "data"), "--out", str(work / "out2"), *opts, "--seed", "1337", "--device", "cpu"],
             cwd=app, timeout=7200)
    m2 = json.loads((work / "out2" / "metrics.json").read_text()) if (work / "out2" / "metrics.json").exists() else {}
    checks.append(check("training is deterministic for a fixed seed", m2.get("evals") == ev and bool(ev)))
    # resume
    half = list(opts)
    half[half.index("--max-iters") + 1] = "150"
    run([str(app / "nanogpt"), "train", "--data", str(work / "data"), "--out", str(work / "out3"), *half, "--seed", "1337", "--device", "cpu"], cwd=app, timeout=7200)
    t3 = run([str(app / "nanogpt"), "train", "--data", str(work / "data"), "--out", str(work / "out3"), *opts, "--seed", "1337", "--device", "cpu", "--resume"], cwd=app, timeout=7200)
    m3 = json.loads((work / "out3" / "metrics.json").read_text()) if (work / "out3" / "metrics.json").exists() else {}
    last = (m3.get("evals") or [{}])[-1]
    checks.append(check("--resume continues to max_iters with a comparable final val loss", t3.returncode == 0 and last.get("iter") == 300
                        and abs(last.get("val_loss", 99) - r["evals"][-1]["val_loss"]) <= 0.15 * r["evals"][-1]["val_loss"], last))
    s = run([str(app / "nanogpt"), "sample", "--out", str(work / "out"), "--num-samples", "2", "--max-new-tokens", "200", "--seed", "7"], cwd=app, timeout=600)
    vocab = set(Path(DATA).read_text())
    text = s.stdout.replace("---------------", "")
    in_vocab = sum(ch in vocab or ch == "\n" for ch in text) / max(1, len(text))
    checks.append(check("sample produces >= 150 chars of text drawn from the vocabulary (>= 95% of output; status lines allowed)",
                        s.returncode == 0 and len(text.strip()) >= 150 and in_vocab >= 0.95, f"{in_vocab:.3f} {s.stdout[:120]!r}"))
    finish(a.out, checks, reference=r, generated=m)


if __name__ == "__main__":
    main()
