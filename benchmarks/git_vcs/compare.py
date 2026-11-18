"""Scripted repository scenarios run with real git and the generated ./ugit; compare ids, outputs, interop."""
import argparse
import os
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from common import check, finish, run  # noqa: E402

# ("w", path, content) writes a file; ("rm", path) deletes; ("c", *args) runs the VCS and records output;
# ("x", *args) runs the VCS without comparing output (state change only); ("id",) records HEAD via real git.
SCENARIO = [
    ("x", "init", "-b", "main"), ("c", "status"),
    ("w", "README.md", "# Project\n\nhello\n"), ("w", "src/app.py", "print('hi')\n" * 3), ("w", "notes.txt", "a\nb\nc\n"),
    ("w", ".gitignore", "*.log\nbuild/\n"), ("w", "debug.log", "x\n"), ("w", "build/out.bin", "bin\n"),
    ("c", "status", "--porcelain"), ("c", "status"), ("x", "add", "."), ("c", "status", "--porcelain"), ("c", "ls-files", "-s"),
    ("c", "commit", "-m", "Initial commit"), ("id",), ("c", "log"), ("c", "cat-file", "-p", "HEAD"), ("c", "ls-tree", "-r", "HEAD"),
    ("c", "cat-file", "-t", "HEAD^{tree}"), ("c", "hash-object", "notes.txt"),
    ("w", "notes.txt", "a\nB\nc\nd\n"), ("w", "src/new.py", "x = 1\n"), ("c", "status", "--porcelain"), ("c", "diff"), ("c", "status"),
    ("x", "add", "-A"), ("c", "diff", "--cached"), ("c", "commit", "-m", "Second: edit notes\n\nWith a body line."), ("id",),
    ("c", "log", "--oneline"), ("c", "log", "--format=%H|%h|%s|%an|%ae|%ad", "-n", "2"), ("c", "show", "HEAD"),
    ("c", "commit", "-m", "nothing"), ("x", "branch", "feature"), ("c", "branch"), ("x", "checkout", "feature"),
    ("w", "feature.txt", "feature work\n"), ("x", "add", "feature.txt"), ("c", "commit", "-m", "Add feature"), ("id",),
    ("x", "checkout", "main"), ("c", "status"), ("c", "merge", "feature"), ("id",), ("c", "log", "--oneline"),
    ("x", "checkout", "-b", "topic"), ("w", "README.md", "# Project\n\nhello\nfrom topic\n"), ("x", "commit", "-a", "-m", "Topic edit"),
    ("x", "checkout", "main"), ("w", "src/app.py", "print('hi')\nprint('main')\n"), ("x", "commit", "-a", "-m", "Main edit"),
    ("c", "merge", "topic"), ("id",), ("c", "cat-file", "-p", "HEAD"), ("c", "log", "--oneline", "-n", "5"),
    ("x", "checkout", "-b", "conflict"), ("w", "notes.txt", "conflict side\n"), ("x", "commit", "-a", "-m", "Conflict A"),
    ("x", "checkout", "main"), ("w", "notes.txt", "main side\n"), ("x", "commit", "-a", "-m", "Conflict B"), ("id",),
    ("c", "merge", "conflict"), ("c", "status", "--porcelain"), ("file", "notes.txt"), ("x", "reset", "--hard", "HEAD"), ("c", "status", "--porcelain"),
    ("x", "tag", "v1.0"), ("x", "tag", "-a", "v1.1", "-m", "Release 1.1"), ("c", "tag"), ("c", "cat-file", "-p", "v1.1"), ("c", "rev-parse", "HEAD~2"),
    ("c", "rev-parse", "v1.0"), ("x", "rm", "notes.txt"), ("x", "mv", "README.md", "README.txt"), ("c", "status", "--porcelain"),
    ("x", "commit", "-m", "Rename and remove"), ("id",), ("c", "diff", "HEAD~1", "HEAD"), ("x", "reset", "--soft", "HEAD~1"), ("c", "status", "--porcelain"),
    ("x", "commit", "-m", "Rename and remove (again)"), ("id",), ("x", "checkout", "HEAD~1", "--", "src/app.py"), ("c", "status", "--porcelain"),
    ("x", "restore", "--staged", "src/app.py"), ("c", "status", "--porcelain"), ("x", "branch", "-d", "feature"), ("c", "branch"),
]

ENV = {"GIT_AUTHOR_NAME": "Ada Lovelace", "GIT_AUTHOR_EMAIL": "ada@example.com", "GIT_AUTHOR_DATE": "@1700000000 +0000",
       "GIT_COMMITTER_NAME": "Ada Lovelace", "GIT_COMMITTER_EMAIL": "ada@example.com", "GIT_COMMITTER_DATE": "@1700000000 +0000",
       "GIT_CONFIG_NOSYSTEM": "1", "LANG": "C", "LC_ALL": "C", "TZ": "UTC", "GIT_PAGER": "cat", "PAGER": "cat", "TERM": "dumb"}


def play(vcs: list[str], repo: Path, home: Path):
    env = dict(os.environ, HOME=str(home), **ENV)
    out, step_time = [], 0
    for i, op in enumerate(SCENARIO):
        # advance the clock per commit so commit ids depend on ordering, identically for both tools
        t = f"@{1700000000 + i * 60} +0000"
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = t
        if op[0] == "w":
            p = repo / op[1]
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(op[2])
        elif op[0] == "file":
            out.append(("file", (repo / op[1]).read_text() if (repo / op[1]).exists() else None))
        elif op[0] == "id":
            r = run(["git", "rev-parse", "HEAD"], cwd=repo, env=env, timeout=30)
            out.append(("id", r.stdout.strip()))
        else:
            r = run(vcs + list(op[1:]), cwd=repo, env=env, timeout=60)
            out.append((" ".join(op[1:]), (r.stdout if op[0] == "c" else None), r.returncode))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", required=True)
    ap.add_argument("--reference", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    app = Path(a.app).resolve()
    gen = [str(app / "ugit")]
    checks = []
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        (d / "ref").mkdir(); (d / "app").mkdir(); (d / "home").mkdir()
        ref_out = play(["git"], d / "ref", d / "home")
        app_out = play(gen, d / "app", d / "home")
        for i, (r, g) in enumerate(zip(ref_out, app_out)):
            if r[0] == "id":
                checks.append(check(f"step {i:02d}: commit id identical to git", r == g, f"{g[1]} vs {r[1]}"))
            elif r[0] == "file":
                checks.append(check(f"step {i:02d}: conflict file content identical", r == g, f"{g[1]!r} vs {r[1]!r}"))
            elif r[1] is not None:
                checks.append(check(f"step {i:02d}: `{r[0][:50]}` output and exit status identical", r == g,
                                    f"got rc={g[2]} {g[1]!r:.300}\nexpected rc={r[2]} {r[1]!r:.300}"))
            else:
                checks.append(check(f"step {i:02d}: `{r[0][:50]}` exit status identical", r[2] == g[2], f"{g[2]} vs {r[2]}"))
        env = dict(os.environ, HOME=str(d / "home"), **ENV)
        f = run(["git", "fsck", "--strict", "--no-dangling"], cwd=d / "app", env=env, timeout=120)
        checks.append(check("real `git fsck --strict` accepts the generated repository", f.returncode == 0, f.stdout[-300:] + f.stderr[-300:]))
        rs = run(["git", "status", "--porcelain"], cwd=d / "app", env=env, timeout=30)
        checks.append(check("real git reads the generated index (status clean/consistent)", rs.returncode == 0 and rs.stdout == run(["git", "status", "--porcelain"], cwd=d / "ref", env=env).stdout, rs.stdout[:200] + rs.stderr[:200]))
        rl = run(["git", "log", "--format=%H %s", "--all"], cwd=d / "app", env=env, timeout=30)
        rr = run(["git", "log", "--format=%H %s", "--all"], cwd=d / "ref", env=env, timeout=30)
        checks.append(check("real git log --all on generated repo identical", rl.stdout == rr.stdout and rl.returncode == 0, rl.stderr[-200:]))
        # generated tool reading a repository written (and packed) by real git
        run(["git", "gc", "-q", "--aggressive"], cwd=d / "ref", env=env, timeout=120)
        for args in (["log", "--oneline"], ["cat-file", "-p", "HEAD~3"], ["ls-tree", "-r", "HEAD"], ["status", "--porcelain"], ["rev-parse", "v1.1"]):
            g = run(gen + args, cwd=d / "ref", env=env, timeout=60)
            r = run(["git"] + args, cwd=d / "ref", env=env, timeout=60)
            checks.append(check(f"reads git-packed repo: {' '.join(args)}", g.stdout == r.stdout and g.returncode == r.returncode, f"{g.stdout[:200]!r} {g.stderr[:200]!r}"))
        g = run(gen + ["status"], cwd=str(d), env=env, timeout=30)
        r = run(["git", "status"], cwd=str(d), env=env, timeout=30)
        checks.append(check("outside a repository: same fatal error and exit status 128", g.returncode == r.returncode == 128 and g.stderr.strip() == r.stderr.strip(), g.stderr[:200]))
    finish(a.out, checks)


if __name__ == "__main__":
    main()
