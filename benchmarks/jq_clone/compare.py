"""Run jq's own test files (tests/jq.test, man.test, ...) through the generated ./jq and the reference jq."""
import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from common import check, finish, run  # noqa: E402

FILES = ["jq.test", "man.test", "base64.test", "uri.test", "onig.test", "manonig.test"]


def parse_tests(path: Path):
    lines = path.read_text().splitlines()
    i, cases = 0, []
    while i < len(lines):
        line = lines[i]
        if not line.strip() or line.startswith("#"):
            i += 1
            continue
        if line.startswith("%%FAIL"):
            prog = lines[i + 1]
            i += 2
            while i < len(lines) and lines[i].strip():
                i += 1
            cases.append({"fail": True, "program": prog})
            continue
        prog, inp = line, lines[i + 1] if i + 1 < len(lines) else "null"
        i += 2
        exp = []
        while i < len(lines) and lines[i].strip() and not lines[i].startswith("#"):
            exp.append(lines[i])
            i += 1
        cases.append({"fail": False, "program": prog, "input": inp, "expected": exp})
    return cases


def norm(lines):
    out = []
    for l in lines:
        try:
            out.append(json.dumps(json.loads(l), sort_keys=False))
        except json.JSONDecodeError:
            out.append(l.strip())
    return out


def run_case(binary, cwd, c):
    env = dict(os.environ, PAGER="cat", JQ_COLORS="", TZ="UTC")
    if c["fail"]:
        r = run([binary, "-n", c["program"]], cwd=cwd, timeout=10, env=env)
        return r.returncode != 0
    r = run([binary, "-c", c["program"]], cwd=cwd, input=c["input"], timeout=10, env=env)
    if r.returncode != 0:
        return False
    return norm([l for l in r.stdout.splitlines() if l.strip()]) == norm(c["expected"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", required=True)
    ap.add_argument("--reference", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    app, ref = Path(a.app), Path(a.reference)
    gen, refbin = str(app / "jq"), str(ref / "jq")
    checks, detail = [], {}
    for f in FILES:
        cases = parse_tests(ref / "tests" / f)
        with ThreadPoolExecutor(8) as ex:
            r_ok = list(ex.map(lambda c: run_case(refbin, ref / "tests", c), cases))
            g_ok = list(ex.map(lambda c: run_case(gen, ref / "tests", c), cases))
        valid = [i for i, ok in enumerate(r_ok) if ok]  # cases the reference itself passes in this harness
        passed = sum(g_ok[i] for i in valid)
        frac = passed / len(valid) if valid else 0
        detail[f] = {"cases": len(cases), "valid": len(valid), "passed": passed}
        failed_progs = [cases[i]["program"] for i in valid if not g_ok[i]][:6]
        for thr in (0.5, 0.8, 0.95, 1.0):
            checks.append(check(f"{f}: >= {int(thr*100)}% of {len(valid)} cases pass", frac >= thr,
                                f"{passed}/{len(valid)} e.g. failing: {failed_progs}"))
    finish(a.out, checks, details=detail)


if __name__ == "__main__":
    main()
