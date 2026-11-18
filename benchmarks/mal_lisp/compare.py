"""Official mal step tests (runtest.py) against ./run, plus the self-hosted mal-in-mal on top of it."""
import argparse
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from common import check, finish, run  # noqa: E402

STEPS = ["step0_repl", "step1_read_print", "step2_eval", "step3_env", "step4_if_fn_do", "step5_tco",
         "step6_file", "step7_quote", "step8_macros", "step9_try", "stepA_mal"]


def runtest(ref: Path, rundir: Path, step: str, env_extra: dict, timeout_s: int = 1200):
    env = dict(os.environ, STEP=step, **env_extra)
    r = run([sys.executable, str(ref / "runtest.py"), "--rundir", str(rundir), "--test-timeout", "30",
             str(ref / "impls" / "tests" / f"{step}.mal"), "--", "./run"], env=env, timeout=timeout_s)
    out = (r.stdout or "") + (r.stderr or "")
    g = lambda k: int(m.group(1)) if (m := re.search(rf"(\d+): {k}", out)) else 0
    return g("passing tests"), g("failing tests"), g("soft failing tests"), g("total tests in the file")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", required=True)
    ap.add_argument("--reference", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    app, ref = Path(a.app).resolve(), Path(a.reference)
    checks, detail = [], {}
    # mal tests expect to run from impls/<impl>/ (they read ../tests/*.mal etc.), so mount the app there
    # (copied, not symlinked: `..` from a symlinked directory resolves to its physical parent)
    layout = Path(tempfile.mkdtemp()) / "impls"
    layout.mkdir()
    shutil.copytree(app, layout / "gen", symlinks=True, ignore=shutil.ignore_patterns(".git", "node_modules", "__pycache__"))
    shutil.copytree(ref / "impls" / "tests", layout / "tests")
    for step in STEPS:
        p, f, soft, total = runtest(ref, layout / "gen", step, {})
        detail[step] = {"passed": p, "failed": f, "soft_failed": soft, "total": total}
        checks.append(check(f"{step}: no hard failures", total > 0 and f == 0 and p > 0, f"{p} passed, {f} failed, {soft} soft of {total}"))
        checks.append(check(f"{step}: all tests incl. optional pass", total > 0 and p == total, f"{p}/{total}"))
    # self-hosting: the mal implementation written in mal, running on the generated stepA
    with tempfile.TemporaryDirectory() as d:
        impls = Path(d) / "impls"
        shutil.copytree(ref / "impls" / "mal", impls / "mal")
        shutil.copytree(layout / "gen", impls / "gen", symlinks=True)
        shutil.copytree(ref / "impls" / "tests", impls / "tests")
        for step in ("step2_eval", "step4_if_fn_do", "step9_try"):
            p, f, soft, total = runtest(ref, impls / "mal", step, {"MAL_IMPL": "gen"}, timeout_s=2400)
            detail["self-hosted " + step] = {"passed": p, "failed": f, "total": total}
            checks.append(check(f"self-hosted mal-in-mal {step}: no hard failures", total > 0 and f == 0 and p > 0, f"{p}/{total}"))
    finish(a.out, checks, details=detail)


if __name__ == "__main__":
    main()
