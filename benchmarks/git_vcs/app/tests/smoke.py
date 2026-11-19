"""Smoke test: run the real ./ugit end-to-end on a throw-away repository."""
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UGIT = os.path.join(ROOT, "ugit")


def run(*args, cwd):
    return subprocess.run([UGIT] + list(args), cwd=cwd, capture_output=True, text=True, check=True).stdout


def main():
    d = tempfile.mkdtemp(prefix="ugit-smoke-")
    try:
        run("init", "repo", cwd=d)
        repo = os.path.join(d, "repo")
        with open(os.path.join(repo, "f"), "w") as f:
            f.write("hello\n")
        sha = run("hash-object", "-w", "f", cwd=repo).strip()
        assert sha == "ce013625030ba8dba906f756967f9e9ca394464a", sha
        assert run("cat-file", "-p", sha, cwd=repo) == "hello\n"
        assert run("cat-file", "-t", sha[:6], cwd=repo) == "blob\n"
        env_ok = {"GIT_AUTHOR_NAME": "S", "GIT_AUTHOR_EMAIL": "s@x", "GIT_COMMITTER_NAME": "S",
                  "GIT_COMMITTER_EMAIL": "s@x", "GIT_AUTHOR_DATE": "@1700000000 +0000",
                  "GIT_COMMITTER_DATE": "@1700000000 +0000"}
        os.environ.update(env_ok)
        run("add", "f", cwd=repo)
        assert run("commit", "-m", "first", cwd=repo).startswith("[master (root-commit) ")
        assert run("log", "--format=%s %an", cwd=repo) == "first S\n"
        with open(os.path.join(repo, "f"), "a") as f:
            f.write("more\n")
        assert "+more" in run("diff", cwd=repo)
        assert run("status", "--porcelain", cwd=repo) == " M f\n"
        run("branch", "topic", cwd=repo)
        run("tag", "-a", "-m", "t", "v1", cwd=repo)
        assert run("tag", cwd=repo) == "v1\n"
        run("checkout", "-b", "feature", cwd=repo)
        with open(os.path.join(repo, "g"), "w") as f:
            f.write("g\n")
        run("add", "g", cwd=repo)
        run("commit", "-m", "feature", cwd=repo)
        run("checkout", "master", cwd=repo)
        assert not os.path.exists(os.path.join(repo, "g"))
        run("add", "-u", cwd=repo)
        run("commit", "-m", "second", cwd=repo)
        assert "Merge made by the 'ort' strategy." in run("merge", "feature", cwd=repo)
        assert os.path.exists(os.path.join(repo, "g"))
        run("reset", "--hard", "HEAD~1", cwd=repo)
        assert run("status", "--porcelain", cwd=repo) == ""
        print("smoke ok")
    finally:
        shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
