"""Run the reference SPI (lsbasi part19) and the generated ./spi on the same Pascal corpus; outputs must match."""
import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from common import check, finish, run  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", required=True)
    ap.add_argument("--reference", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    ref_spi = Path(a.reference) / "part19" / "spi.py"
    progs = sorted((HERE / "corpus").glob("*.pas"))
    for part in ("part14", "part15", "part16", "part17", "part18", "part19"):
        progs += sorted((Path(a.reference) / part).glob("*.pas"))
    checks = []
    for prog in progs:
        for flags in (["--stack"], []):
            r = run([sys.executable, str(ref_spi), str(prog), *flags], timeout=60)
            if r.returncode != 0 and "Traceback" in (r.stderr or ""):
                continue  # the reference itself crashes: behaviour undefined, not a valid comparison case
            g = run(["./spi", str(prog), *flags], cwd=a.app, timeout=60)
            same = g.stdout == r.stdout and (g.returncode == 0) == (r.returncode == 0)
            label = f"{prog.parent.name}/{prog.name} {' '.join(flags) or '(no flags)'}"
            detail = "" if same else f"rc {g.returncode} vs {r.returncode}; got:\n{g.stdout[:300]}\nexpected:\n{r.stdout[:300]}\n{g.stderr[-200:]}"
            checks.append(check(label, same, detail))
    finish(a.out, checks)


if __name__ == "__main__":
    main()
