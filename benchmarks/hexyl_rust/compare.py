"""Build the generated hexyl and the reference; compare byte-exact outputs over a matrix of inputs/options."""
import argparse
import os
import random
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from common import check, finish, run  # noqa: E402

OPTIONS = [[], ["--color=never"], ["--border", "ascii"], ["--border", "none"], ["-p"], ["--no-characters"], ["-P"],
           ["-o", "0x100"], ["-s", "2", "-n", "20"], ["-s", "-10"], ["-n", "0x10"], ["-n", "1KiB"], ["--panels", "1"],
           ["--panels", "3", "--color=never"], ["-g", "2"], ["-g", "4", "--endianness", "little"], ["-g", "8", "--color=never"],
           ["-b", "2"], ["-b", "8", "--color=never"], ["-b", "10"], ["--terminal-width", "60"], ["--terminal-width", "140", "--panels", "auto"],
           ["-v"], ["--character-table", "ascii"], ["--character-table", "braille", "--color=never"], ["--color=never", "-C", "-P", "--border", "ascii"]]


def files(d: Path):
    rng = random.Random(5)
    fs = {
        "hello": b"Hello, World!\x00\x01\x02\xff\x80 tab\there\n",
        "empty": b"",
        "one": b"\x7f",
        "all256": bytes(range(256)),
        "squeeze": b"A" * 64 + b"B" * 3 + b"\x00" * 100,
        "random": bytes(rng.getrandbits(8) for _ in range(300)),
        "text": ("The quick brown fox jumps over the lazy dog.\r\n" * 3).encode(),
    }
    out = {}
    for k, v in fs.items():
        p = d / f"{k}.bin"
        p.write_bytes(v)
        out[k] = p
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", required=True)
    ap.add_argument("--reference", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    app, ref = Path(a.app), Path(a.reference)
    checks = []
    b = run(["cargo", "build", "--release", "-q"], cwd=app, timeout=1800)
    checks.append(check("cargo build --release", b.returncode == 0, b.stderr[-500:]))
    rb = run(["cargo", "build", "--release", "-q"], cwd=ref, timeout=1800)
    gen, refbin = app / "target" / "release" / "hexyl", ref / "target" / "release" / "hexyl"
    if b.returncode != 0 or not gen.exists():
        return finish(a.out, checks)
    env = {k: v for k, v in os.environ.items() if k != "NO_COLOR"}
    with tempfile.TemporaryDirectory() as d:
        fs = files(Path(d))
        for opts in OPTIONS:
            names = ["hello", "squeeze", "random"] if opts else list(fs)
            ok = 0
            bad = None
            for n in names:
                r = run([str(refbin), *opts, str(fs[n])], env=env, text=False, timeout=30)
                g = run([str(gen), *opts, str(fs[n])], env=env, text=False, timeout=30)
                if r.stdout == g.stdout and (r.returncode == 0) == (g.returncode == 0):
                    ok += 1
                elif bad is None:
                    bad = f"{n}: got {g.stdout[:160]!r} expected {r.stdout[:160]!r} {g.stderr[-120:]!r}"
            checks.append(check(f"output identical: hexyl {' '.join(opts) or '(defaults)'}", ok == len(names), f"{ok}/{len(names)} {bad or ''}"))
        r = run([str(refbin), "--color=never"], input=fs["hello"].read_bytes(), text=False, env=env, timeout=30)
        g = run([str(gen), "--color=never"], input=fs["hello"].read_bytes(), text=False, env=env, timeout=30)
        checks.append(check("stdin input identical", r.stdout == g.stdout, ""))
        r = run([str(refbin), str(fs["hello"])], env=dict(env, NO_COLOR="1"), text=False, timeout=30)
        g = run([str(gen), str(fs["hello"])], env=dict(env, NO_COLOR="1"), text=False, timeout=30)
        checks.append(check("NO_COLOR respected", r.stdout == g.stdout, ""))
        g = run([str(gen), "/nonexistent/file"], timeout=30)
        checks.append(check("missing file -> non-zero exit and stderr message", g.returncode != 0 and bool(g.stderr.strip()), g.stderr[-200:]))
    t = run(["cargo", "test", "-q"], cwd=app, timeout=1800)
    checks.append(check("own cargo test passes", t.returncode == 0, t.stdout[-300:] + t.stderr[-300:]))
    finish(a.out, checks)


if __name__ == "__main__":
    main()
