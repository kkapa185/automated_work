import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JQ = os.path.join(ROOT, "jq")
sys.path.insert(0, ROOT)


def run_jq(args, stdin="", env=None, expect_rc=None):
    e = dict(os.environ)
    e["PAGER"] = "less"
    if env:
        e.update(env)
    p = subprocess.run([sys.executable, JQ] + list(args), input=stdin.encode("utf-8"),
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=e, timeout=20)
    if expect_rc is not None:
        assert p.returncode == expect_rc, (p.returncode, p.stderr.decode())
    return p.returncode, p.stdout.decode("utf-8"), p.stderr.decode("utf-8")


@pytest.fixture
def jq():
    return run_jq


def jq_out(prog, inp="null", *opts):
    rc, out, err = run_jq(list(opts) + ["-c", prog], inp)
    assert rc == 0, err
    return out


def evaluate(prog, inp=None, vars=None):
    """In-process evaluation on a big-stack thread; returns the list of outputs."""
    import threading
    sys.setrecursionlimit(1000000)
    threading.stack_size(512 * 1024 * 1024)
    box = []

    def target():
        try:
            box.append((True, _evaluate(prog, inp, vars)))
        except BaseException as e:  # re-raised in the caller
            box.append((False, e))
    t = threading.Thread(target=target)
    t.start()
    t.join()
    ok, val = box[0]
    if not ok:
        raise val
    return val


def _evaluate(prog, inp=None, vars=None):
    from jqpy.parser import parse
    from jqpy.interp import Compiler, Scope, Env
    from jqpy.builtins import BUILTINS
    _, _, body = parse(prog)
    sc = None
    env = None
    for k, v in (vars or {}).items():
        sc = Scope("v", k, 0, sc)
        env = Env(env, "$" + k, v)
    fn = Compiler(BUILTINS).compile(body, sc)
    return [v for _, v in fn(env, None, inp)]


def j(text):
    """Parse a (possibly multi-value) JSON text into a list of values."""
    import json
    dec = json.JSONDecoder()
    text = text.strip()
    out, i = [], 0
    while i < len(text):
        v, k = dec.raw_decode(text, i)
        out.append(v)
        i = k
        while i < len(text) and text[i].isspace():
            i += 1
    return out
