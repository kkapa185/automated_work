"""Compile the reference jsmn test-suite and a differential fuzzer against both headers."""
import argparse
import random
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from common import check, finish, run  # noqa: E402

CONFIGS = {"default": [], "strict": ["-DJSMN_STRICT=1"], "links": ["-DJSMN_PARENT_LINKS=1"],
           "strict_links": ["-DJSMN_STRICT=1", "-DJSMN_PARENT_LINKS=1"]}


def corpus(n=700):
    rng = random.Random(3)
    atoms = ['{', '}', '[', ']', ':', ',', '"a"', '"b\\"c"', '"\\u00e9"', '"\\x"', '1', '-2.5e3', 'true', 'false',
             'null', 'tru', ' ', '\n', '"', 'abc', '01', '"k":', '{"x":', '[1,', '\\', '"\\n\\t"']
    out = ['{}', '[]', '{"a":[1,2,{"b":null}],"c":"d"}', '[[[[[]]]]]', '{"a":1,"b":2}x']
    for _ in range(n):
        out.append("".join(rng.choice(atoms) for _ in range(rng.randint(1, 12))))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", required=True)
    ap.add_argument("--reference", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    app, ref = Path(a.app), Path(a.reference)
    checks = []
    hdr = next((p for p in [app / "jsmn.h", app / "include" / "jsmn.h", app / "src" / "jsmn.h"] if p.exists()), None)
    checks.append(check("jsmn.h found", hdr is not None, str(hdr)))
    if hdr is None:
        return finish(a.out, checks)
    data = "\0".join(corpus()).encode()
    for cfg, flags in CONFIGS.items():
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "test").mkdir()
            for f in ("tests.c", "test.h", "testutil.h"):
                shutil.copy(ref / "test" / f, d / "test" / f)
            shutil.copy(hdr, d / "jsmn.h")
            c = run(["cc", "-Wall", *flags, "test/tests.c", "-o", "t"], cwd=d, timeout=120)
            r = run(["./t"], cwd=d, timeout=60) if c.returncode == 0 else c
            checks.append(check(f"reference test-suite passes [{cfg}]", c.returncode == 0 and r.returncode == 0,
                                (r.stdout[-300:] + r.stderr[-300:]) if r.returncode else ""))
            outs = {}
            for label, h in (("ref", ref / "jsmn.h"), ("app", hdr)):
                shutil.copy(h, d / "jsmn.h")
                shutil.copy(HERE / "fuzz_driver.c", d / "fz.c")
                cc = run(["cc", "-O1", *flags, "fz.c", "-o", "fz_" + label], cwd=d, timeout=120)
                rr = run(["./fz_" + label], cwd=d, input=data.decode("latin-1"), timeout=60) if cc.returncode == 0 else cc
                outs[label] = rr.stdout.splitlines()
            same = sum(x == y for x, y in zip(outs["ref"], outs["app"]))
            total = len(outs["ref"])
            bad = [i for i, (x, y) in enumerate(zip(outs["ref"], outs["app"])) if x != y][:3]
            checks.append(check(f"differential fuzz identical [{cfg}]", total > 0 and same == total and len(outs["app"]) == total,
                                f"{same}/{total} first mismatches {bad}"))
    w = run(["cc", "-std=c89", "-pedantic", "-Wall", "-Wextra", "-Werror", "-fsyntax-only", "-x", "c", str(hdr)], timeout=60)
    checks.append(check("header compiles as strict C89 with -Wall -Wextra -Werror", w.returncode == 0, w.stderr[-400:]))
    mk = run(["make", "test"], cwd=app, timeout=300)
    checks.append(check("own `make test` passes", mk.returncode == 0, mk.stderr[-300:]))
    finish(a.out, checks)


if __name__ == "__main__":
    main()
