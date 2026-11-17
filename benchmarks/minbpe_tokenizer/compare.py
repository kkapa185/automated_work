"""Train both implementations on the same corpus and compare merges, token ids and saved models."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common import check, finish, run_python_driver  # noqa: E402

DRIVER = r'''
import json, sys, tempfile, os, time
from minbpe import BasicTokenizer, RegexTokenizer
cfg = json.loads(sys.stdin.read())
text = open(cfg["corpus"], encoding="utf-8").read()
probe = cfg["probes"]
out = {}
for name, cls in (("basic", BasicTokenizer), ("regex", RegexTokenizer)):
    t = cls()
    t0 = time.time()
    t.train(text, cfg["vocab"])
    out[name + "_train_s"] = time.time() - t0
    out[name + "_merges"] = [[a, b, i] for (a, b), i in sorted(t.merges.items(), key=lambda kv: kv[1])]
    out[name + "_ids"] = [t.encode(p) for p in probe]
    out[name + "_roundtrip"] = all(t.decode(t.encode(p)) == p for p in probe)
    d = tempfile.mkdtemp()
    t.save(os.path.join(d, "tok"))
    out[name + "_model"] = open(os.path.join(d, "tok.model"), encoding="utf-8").read()
    t2 = cls(); t2.load(os.path.join(d, "tok.model"))
    out[name + "_reload_ids"] = [t2.encode(p) for p in probe]
r = RegexTokenizer(); r.train(text[:20000], 300)
r.register_special_tokens({"<|endoftext|>": 100257, "<|fim|>": 100258})
s = "<|endoftext|>Hello world<|fim|> again <|endoftext|>"
out["special_all"] = r.encode(s, allowed_special="all")
out["special_none"] = r.encode(s, allowed_special="none")
try:
    r.encode(s); out["special_raise"] = False
except Exception:
    out["special_raise"] = True
print(json.dumps(out))
'''

PROBES = ["", "?", "hello world!!!? (안녕하세요!) lol123 😉", "Taylor Swift's \"Shake It Off\"\n\n  tabs\tand\r\nnewlines",
          "ünïcödé ✓ \x00\x07 control", "1234567890 numbers 3.14159", "the the the the theThe THE"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", required=True)
    ap.add_argument("--reference", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    corpus = str(Path(a.reference) / "tests" / "taylorswift.txt")
    probes = PROBES + [Path(corpus).read_text(encoding="utf-8")[5000:9000]]
    payload = {"corpus": corpus, "vocab": 512, "probes": probes}
    ref = run_python_driver(DRIVER, a.reference, a.reference, payload, timeout=1200)
    got = run_python_driver(DRIVER, a.app, a.app, payload, timeout=1200)
    checks = [check("driver runs against generated package", "__error__" not in got, got.get("__error__", ""))]
    if "__error__" not in got:
        for n in ("basic", "regex"):
            checks.append(check(f"{n}: 256 learned merges identical", got[f"{n}_merges"] == ref[f"{n}_merges"],
                                f"first diff at {next((i for i, (x, y) in enumerate(zip(got[n + '_merges'], ref[n + '_merges'])) if x != y), None)}"))
            checks.append(check(f"{n}: encode ids identical on probes", got[f"{n}_ids"] == ref[f"{n}_ids"]))
            checks.append(check(f"{n}: decode(encode(x)) == x", got[f"{n}_roundtrip"]))
            checks.append(check(f"{n}: .model file identical", got[f"{n}_model"] == ref[f"{n}_model"]))
            checks.append(check(f"{n}: load() reproduces encodings", got[f"{n}_reload_ids"] == ref[f"{n}_ids"]))
            checks.append(check(f"{n}: training time <= 3x reference (+5s)", got[f"{n}_train_s"] <= 3 * ref[f"{n}_train_s"] + 5,
                                f"{got[n + '_train_s']:.1f}s vs {ref[n + '_train_s']:.1f}s"))
        for k in ("special_all", "special_none", "special_raise"):
            checks.append(check(f"special tokens: {k}", got[k] == ref[k], f"{got[k]} vs {ref[k]}"))
    finish(a.out, checks)


if __name__ == "__main__":
    main()
