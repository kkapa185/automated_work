"""Run official Lua test files and an output-comparison corpus with the reference lua and the generated ./lua."""
import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from common import check, finish, run  # noqa: E402

TESTES = ["bitwise", "calls", "closure", "constructs", "coroutine", "events", "goto", "literals", "locals",
          "math", "nextvar", "pm", "sort", "strings", "tpack", "utf8", "vararg", "errors"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", required=True)
    ap.add_argument("--reference", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    app, ref = Path(a.app).resolve(), Path(a.reference)
    gen, refbin = str(app / "lua"), str(ref / "lua")
    checks = []
    for prog in sorted((HERE / "corpus").glob("*.lua")):
        r = run([refbin, str(prog)], cwd=str(HERE / "corpus"), timeout=60)
        g = run([gen, str(prog)], cwd=str(HERE / "corpus"), timeout=120)
        same_out = r.stdout == g.stdout
        first = lambda e, exe: (e.splitlines() or [""])[0].replace(exe + ":", "lua:", 1)
        same_err = (r.returncode == 0) == (g.returncode == 0) and first(r.stderr, refbin) == first(g.stderr, gen)
        checks.append(check(f"corpus {prog.name}: stdout identical", same_out, "" if same_out else f"got:\n{g.stdout[-400:]}\nexpected:\n{r.stdout[-400:]}\n{g.stderr[-200:]}"))
        checks.append(check(f"corpus {prog.name}: exit status and first error line identical", same_err, f"{g.returncode} {g.stderr[:150]!r} vs {r.returncode} {r.stderr[:150]!r}"))
    for t in TESTES:
        g = run([gen, f"{t}.lua"], cwd=str(ref / "testes"), timeout=300)
        checks.append(check(f"official testes/{t}.lua passes", g.returncode == 0, (g.stdout[-200:] + g.stderr[-300:]) if g.returncode else ""))
    finish(a.out, checks)


if __name__ == "__main__":
    main()
