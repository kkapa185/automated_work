"""Hidden acceptance harness for the AGC assembler benchmark.

Ground truth: the proof-read octal listings of the real Apollo 11 ropes (Virtual AGC `*.binsource`, which
were checked word-by-word against the original printed YUL listings). The generated assembler is run on
the Apollo-11 repository sources and its rope is compared word by word.
"""
import argparse
import json
import re
import subprocess
import time
from pathlib import Path

GROUND_TRUTH = {
    "Comanche055": Path("/home/user/reference/virtualagc/Comanche055/Comanche055.binsource"),
    "Luminary099": Path("/home/user/reference/virtualagc/Luminary099/Luminary099.binsource"),
}


def parse_binsource(path: Path) -> dict[int, list[str]]:
    banks: dict[int, list[str]] = {}
    cur = None
    for raw in path.read_text(errors="replace").splitlines():
        line = raw.split(";")[0].strip()
        if not line:
            continue
        m = re.match(r"BANK\s*=\s*([0-7]+)", line)
        if m:
            cur = int(m.group(1), 8)
            banks[cur] = []
            continue
        if cur is not None:
            banks[cur].extend(line.split())
    return banks


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", required=True)
    ap.add_argument("--reference", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    app = Path(a.app)
    checks, details = [], {}
    scores = []
    for prog, truth_path in GROUND_TRUTH.items():
        out = app / "_bench_out" / f"{prog}.binsource"
        out.parent.mkdir(exist_ok=True)
        sym = app / "_bench_out" / f"{prog}.symbols.json"
        t0 = time.time()
        try:
            proc = subprocess.run(["./agcasm", "assemble", f"agc_source/{prog}/MAIN.agc", "-o", str(out),
                                   "--symbols", str(sym)], cwd=app, capture_output=True, text=True, timeout=900)
            rc, err = proc.returncode, proc.stderr[-3000:]
        except Exception as exc:  # noqa: BLE001
            rc, err = -1, repr(exc)
        dt = round(time.time() - t0, 1)
        checks.append({"name": f"{prog}: assembles (exit 0)", "passed": rc == 0, "detail": f"rc={rc} in {dt}s {err[-500:]}"})
        truth = parse_binsource(truth_path)
        got = parse_binsource(out) if out.exists() else {}
        total = match = used_total = used_match = 0
        per_bank = {}
        for bank, words in truth.items():
            g = got.get(bank, [])
            bm = 0
            for i, w in enumerate(words):
                gw = g[i] if i < len(g) else None
                total += 1
                same = gw is not None and (gw == w or (w != "@" and gw != "@" and int(gw, 8) == int(w, 8)))
                match += same
                bm += same
                if w != "@":
                    used_total += 1
                    used_match += same
            per_bank[f"{bank:02o}"] = round(bm / len(words), 4)
        exact_banks = sum(1 for v in per_bank.values() if v == 1.0)
        frac = used_match / used_total if used_total else 0.0
        scores.append(frac)
        details[prog] = {"word_match_used": round(frac, 5), "word_match_all": round(match / total, 5) if total else 0,
                         "exact_banks": exact_banks, "per_bank": per_bank}
        checks.append({"name": f"{prog}: rope words identical to Apollo 11 listing", "passed": frac == 1.0,
                       "detail": f"{used_match}/{used_total} used words match; {exact_banks}/36 banks exact"})
        checks.append({"name": f"{prog}: rope has 36 banks x 1024 words", "passed": len(got) == 36 and all(len(v) == 1024 for v in got.values()),
                       "detail": f"banks={len(got)}"})
        n_sym = 0
        if sym.exists():
            try:
                n_sym = len(json.loads(sym.read_text()))
            except Exception:  # noqa: BLE001
                n_sym = -1
        checks.append({"name": f"{prog}: symbol table emitted", "passed": n_sym > 1000, "detail": f"{n_sym} symbols"})
    result = {"score": round(sum(scores) / len(scores), 5), "checks": checks, "details": details}
    Path(a.out).write_text(json.dumps(result, indent=2))
    print(json.dumps({k: v for k, v in result.items() if k != "details"}, indent=2))


if __name__ == "__main__":
    main()
