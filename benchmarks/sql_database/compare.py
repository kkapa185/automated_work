"""Run a SQL corpus through the reference sqlite3 shell (built from the repo) and the generated ./sqldb."""
import argparse
import re
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from common import check, finish, run  # noqa: E402

ERR = re.compile(r"^(Parse error|Runtime error|Error)\b", re.M)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", required=True)
    ap.add_argument("--reference", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    app, ref = Path(a.app).resolve(), Path(a.reference)
    gen, refbin = str(app / "sqldb"), str(ref / "bld" / "sqlite3")
    checks = []
    for f in sorted((HERE / "corpus").glob("*.sql")):
        sql = f.read_text()
        r = run([refbin], input=sql, timeout=60)
        g = run([gen], input=sql, timeout=120)
        checks.append(check(f"{f.name}: stdout identical", r.stdout == g.stdout,
                            "" if r.stdout == g.stdout else f"got:\n{g.stdout[:500]}\nexpected:\n{r.stdout[:500]}\n{g.stderr[-200:]}"))
        ne_r, ne_g = len(ERR.findall(r.stderr)), len(ERR.findall(g.stderr or ""))
        checks.append(check(f"{f.name}: same number of statement errors ({ne_r}) and exit status", ne_r == ne_g and r.returncode == g.returncode,
                            f"errors {ne_g} vs {ne_r}, rc {g.returncode} vs {r.returncode}: {(g.stderr or '')[:300]}"))
    # persistence across processes and crash-free reopen
    with tempfile.TemporaryDirectory() as d:
        for label, binary in (("ref", refbin), ("app", gen)):
            db = str(Path(d) / f"{label}.db")
            run([binary, db], input="CREATE TABLE k(a INTEGER PRIMARY KEY, b TEXT); INSERT INTO k(b) VALUES ('one'),('two');"
                                    "BEGIN; INSERT INTO k(b) VALUES ('rolled'); ROLLBACK;", timeout=60)
            run([binary, db], input="INSERT INTO k(b) VALUES ('three'); CREATE INDEX kb ON k(b);", timeout=60)
        r = run([refbin, str(Path(d) / "ref.db")], input="SELECT * FROM k ORDER BY a; SELECT count(*) FROM sqlite_schema;", timeout=60)
        g = run([gen, str(Path(d) / "app.db")], input="SELECT * FROM k ORDER BY a; SELECT count(*) FROM sqlite_schema;", timeout=60)
        checks.append(check("file database persists committed data across processes (rollback not persisted)", r.stdout == g.stdout and g.stdout.strip() != "",
                            f"got {g.stdout!r} expected {r.stdout!r} {(g.stderr or '')[-200:]}"))
    # scale: 20k rows, indexed lookup and aggregate
    script = "CREATE TABLE big(id INTEGER PRIMARY KEY, g INTEGER, v TEXT);\nBEGIN;\n" + "".join(
        f"INSERT INTO big(g, v) VALUES ({i % 97}, 'v{i}');\n" for i in range(20000)) + \
        "COMMIT;\nCREATE INDEX bg ON big(g);\nSELECT count(*), sum(g), max(v) FROM big;\nSELECT g, count(*) FROM big WHERE g IN (3, 50) GROUP BY g;\n" \
        "SELECT count(*) FROM big a JOIN big b ON a.id = b.id WHERE a.g = 5;\n"
    import time
    t0 = time.time()
    g = run([gen], input=script, timeout=300)
    dt = time.time() - t0
    r = run([refbin], input=script, timeout=60)
    checks.append(check("20k-row workload: identical results", g.stdout == r.stdout, f"{g.stdout[:200]!r} vs {r.stdout[:200]!r}"))
    checks.append(check("20k-row workload finishes in < 60 s", dt < 60 and g.returncode == 0, f"{dt:.1f}s"))
    finish(a.out, checks)


if __name__ == "__main__":
    main()
