"""Spec examples, pathological-input performance tests and real-world documents vs reference cmark."""
import argparse
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from common import check, finish, run  # noqa: E402

REAL_DOCS = sorted(Path("/home/user/reference").glob("*/README.md")) + sorted(Path("/home/user/reference").glob("*/docs/*.md"))[:20]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", required=True)
    ap.add_argument("--reference", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    app, ref = Path(a.app), Path(a.reference)
    gen, refbin = str(app / "cmark"), str(ref / "build" / "src" / "cmark")
    checks = []
    # 1) the spec examples through the official runner
    r = run([sys.executable, "test/spec_tests.py", "--spec", "test/spec.txt", "--program", gen], cwd=ref, timeout=1800)
    m = re.search(r"(\d+) passed, (\d+) failed, (\d+) errored", r.stdout)
    passed, total = (int(m.group(1)), sum(int(x) for x in m.groups())) if m else (0, 652)
    for thr in (0.5, 0.8, 0.95, 1.0):
        checks.append(check(f"spec examples: >= {int(thr*100)}% pass", passed >= thr * total, f"{passed}/{total}"))
    for extra in ("smart_punct.txt", "regression.txt"):
        r = run([sys.executable, "test/spec_tests.py", "--spec", f"test/{extra}", "--program",
                 f"{gen} --smart" if extra == "smart_punct.txt" else gen], cwd=ref, timeout=600)
        m = re.search(r"(\d+) passed, (\d+) failed, (\d+) errored", r.stdout)
        p, t = (int(m.group(1)), sum(int(x) for x in m.groups())) if m else (0, 1)
        checks.append(check(f"{extra}: all examples pass", t > 0 and p == t, f"{p}/{t}"))
    # 2) pathological inputs: correctness + linear time (the reference runner applies a timeout)
    r = run([sys.executable, "pathological_tests.py", "--program", gen], cwd=ref / "test", timeout=1800)
    out = (r.stdout or "") + "\n" + (r.stderr or "")
    pm = re.findall(r"^(.*?)\s*\[(PASSED|FAILED|TIMEOUT|ERRORED)\]", out, re.M)
    np = sum(1 for _, s in pm if s == "PASSED")
    checks.append(check("pathological inputs: >= 80% pass (correct and fast)", pm and np >= 0.8 * len(pm), f"{np}/{len(pm)}"))
    checks.append(check("pathological inputs: all pass", pm and np == len(pm), f"{np}/{len(pm)} {[n for n, s in pm if s != 'PASSED'][:6]}"))
    # 3) real-world documents: byte-identical HTML to reference cmark
    same = 0
    bad = []
    for d in REAL_DOCS:
        rr = run([refbin, str(d)], timeout=60)
        gg = run([gen, str(d)], timeout=60)
        if rr.stdout == gg.stdout and gg.returncode == 0:
            same += 1
        else:
            bad.append(d.parent.name)
    checks.append(check(f"real-world documents: >= 80% byte-identical ({len(REAL_DOCS)} docs)", same >= 0.8 * len(REAL_DOCS), f"{same}/{len(REAL_DOCS)} differing: {bad[:8]}"))
    checks.append(check("real-world documents: all byte-identical", same == len(REAL_DOCS), f"{same}/{len(REAL_DOCS)}"))
    for opt in ("--unsafe", "--smart", "--hardbreaks", "--sourcepos"):
        d = REAL_DOCS[0]
        rr, gg = run([refbin, opt, str(d)], timeout=60), run([gen, opt, str(d)], timeout=60)
        checks.append(check(f"option {opt} identical on a real document", rr.stdout == gg.stdout and gg.returncode == 0))
    finish(a.out, checks)


if __name__ == "__main__":
    main()
