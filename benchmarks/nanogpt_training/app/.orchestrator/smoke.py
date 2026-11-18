"""Smoke test: prepare + tiny train + sample on the bundled corpus."""
import os
import subprocess
import sys
import tempfile

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
exe = os.path.join(root, "nanogpt")
with tempfile.TemporaryDirectory() as d:
    data, out = os.path.join(d, "data"), os.path.join(d, "out")
    for args in (["prepare", "--input", os.path.join(root, "data", "input.txt"), "--out", data],
                 ["train", "--data", data, "--out", out, "--n-layer", "2", "--n-head", "2", "--n-embd", "32",
                  "--block-size", "32", "--batch-size", "8", "--max-iters", "20", "--eval-interval", "10",
                  "--eval-iters", "5"],
                 ["sample", "--out", out, "--num-samples", "2", "--max-new-tokens", "50"]):
        r = subprocess.run([exe, *args], capture_output=True, text=True)
        print(r.stdout, r.stderr)
        if r.returncode:
            sys.exit(r.returncode)
