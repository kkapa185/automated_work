"""Every example in docs/manual.yml, run end-to-end through ./jq."""
import json
import os

import pytest
import yaml

from conftest import ROOT, run_jq

with open(os.path.join(ROOT, "docs", "manual.yml")) as fh:
    DOC = yaml.safe_load(fh)


def _collect():
    cases = []

    def walk(x, title):
        if isinstance(x, dict):
            t = x.get("title", title)
            for ex in x.get("examples", []) or []:
                cases.append((t, ex))
            for v in x.values():
                walk(v, t)
        elif isinstance(x, list):
            for v in x:
                walk(v, title)
    walk(DOC, "")
    return cases


CASES = _collect()


def _values(text):
    dec = json.JSONDecoder()
    i, out = 0, []
    text = text.strip()
    while i < len(text):
        v, j = dec.raw_decode(text, i)
        out.append(v)
        i = j
        while i < len(text) and text[i].isspace():
            i += 1
    return out


@pytest.mark.parametrize("title,ex", CASES, ids=[
    "%03d-%s" % (i, c[1]["program"][:30].replace("/", "_")) for i, c in enumerate(CASES)])
def test_manual_example(title, ex):
    rc, out, err = run_jq(["-c", ex["program"]], ex.get("input", "null") or "null")
    assert rc == 0, err
    expected = [json.loads(o) if False else _values(o)[0] for o in ex.get("output", [])]
    got = _values(out) if out.strip() else []
    assert got == expected, "program %r input %r" % (ex["program"], ex.get("input"))
