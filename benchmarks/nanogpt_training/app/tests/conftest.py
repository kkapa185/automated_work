import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

CORPUS = ("To be, or not to be, that is the question:\nWhether 'tis nobler in the mind to suffer\n" * 12)

TINY = ["--n-layer", "2", "--n-head", "2", "--n-embd", "16", "--block-size", "16", "--batch-size", "4",
        "--eval-iters", "3", "--eval-interval", "5", "--warmup-iters", "2", "--dropout", "0.1"]


def run_cli(*args, check=True):
    r = subprocess.run([os.path.join(ROOT, "nanogpt"), *map(str, args)], capture_output=True, text=True, cwd=ROOT)
    if check:
        assert r.returncode == 0, r.stderr
    return r


@pytest.fixture(scope="session")
def prepared(tmp_path_factory):
    d = tmp_path_factory.mktemp("prep")
    (d / "in.txt").write_text(CORPUS)
    run_cli("prepare", "--input", d / "in.txt", "--out", d / "data")
    return d / "data"
