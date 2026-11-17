"""Run the reference slugify test-suite against the generated package and fuzz both implementations."""
import argparse
import json
import random
import re
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from common import check, finish, run  # noqa: E402

FUZZ = r'''
import slugify, {slugifyWithCounter} from %s;
const inputs = JSON.parse(process.argv[2]);
const out = inputs.map(([s, o]) => { try { return slugify(s, o); } catch (e) { return 'ERR:' + e.constructor.name; } });
const c = slugifyWithCounter();
const counter = ['foo bar', 'foo bar', 'foo-bar-2', 'foo bar', 'baz', 'foo-2', 'foo', 'foo'].map(s => c(s));
c.reset();
counter.push(c('foo bar'));
console.log(JSON.stringify({out, counter}));
'''


def entry(app: Path) -> Path | None:
    pkg = app / "package.json"
    if pkg.exists():
        d = json.loads(pkg.read_text())
        ex = d.get("exports")
        if isinstance(ex, dict):
            ex = ex.get(".", ex)
            if isinstance(ex, dict):
                ex = ex.get("import") or ex.get("default")
        cand = ex or d.get("module") or d.get("main")
        if isinstance(cand, str) and (app / cand).exists():
            return app / cand
    for c in ("index.js", "index.mjs", "src/index.js"):
        if (app / c).exists():
            return app / c
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", required=True)
    ap.add_argument("--reference", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    app, ref = Path(a.app), Path(a.reference)
    checks = []
    e = entry(app)
    checks.append(check("package entry point found", e is not None, str(e)))
    deps = json.loads((app / "package.json").read_text()).get("dependencies", {}) if (app / "package.json").exists() else {}
    checks.append(check("no slug/transliteration library dependency", not any("sindresorhus" in d or "slug" in d or "translit" in d for d in deps), deps))
    if e is None:
        return finish(a.out, checks)
    # 1) reference test-suite against the generated implementation
    test_src = (ref / "test.js").read_text().replace("'./index.js'", json.dumps(str(e)))
    tf = app / "_bench_reference_test.mjs"
    tf.write_text(test_src)
    r = run(["node", "--test", "--test-reporter=tap", str(tf)], cwd=app, timeout=300)
    blocks = re.findall(r"^(not ok|ok) \d+ - (.+)$", r.stdout, re.M)
    for status, name in blocks:
        checks.append(check(f"reference test: {name}", status == "ok"))
    if not blocks:
        checks.append(check("reference test-suite runs", False, r.stderr[-500:]))
    # 2) differential fuzzing
    rng = random.Random(7)
    pool = list("abcXYZ09 _-.,!?&@#'’\"♥🦄") + list("äöüßÄÖÜåøæéèêçñœÿ") + list("жщюяЖЩЮЯёЁ") + list("αβγδΩ") + list("ăâđêôơưĂ") + list("şğıİ") + ["fooBar", "APIKey", "XMLHttp", "foo360BAR", "  ", "--", "__"]
    inputs = []
    for i in range(600):
        s = "".join(rng.choice(pool) for _ in range(rng.randint(0, 14)))
        o = rng.choice([{}, {"separator": "_"}, {"separator": ""}, {"lowercase": False}, {"decamelize": False},
                        {"preserveLeadingUnderscore": True}, {"preserveTrailingDash": True}, {"locale": "de"},
                        {"transliterate": False}, {"customReplacements": [["@", " at "]]}, {"preserveCharacters": ["#"]}])
        inputs.append([s, o])
    res = {}
    for label, mod in (("ref", ref / "index.js"), ("app", e)):
        f = (app if label == "app" else ref) / "_bench_fuzz.mjs"
        f.write_text(FUZZ % json.dumps(str(mod)))
        p = run(["node", str(f), json.dumps(inputs)], cwd=f.parent, timeout=120)
        try:
            res[label] = json.loads(p.stdout.strip().splitlines()[-1])
        except Exception:  # noqa: BLE001
            res[label] = {"out": [], "counter": [], "err": p.stderr[-400:]}
    same = sum(x == y for x, y in zip(res["ref"]["out"], res["app"]["out"]))
    mism = [(inputs[i], res["ref"]["out"][i], res["app"]["out"][i]) for i in range(min(len(res["app"]["out"]), len(inputs))) if res["ref"]["out"][i] != res["app"]["out"][i]][:8]
    checks.append(check("differential fuzz (600 inputs): >= 95% identical to reference", same >= 0.95 * len(inputs), f"{same}/{len(inputs)} e.g. {mism}"))
    checks.append(check("differential fuzz: 100% identical", same == len(inputs), f"{same}/{len(inputs)}"))
    checks.append(check("slugifyWithCounter identical", res["app"].get("counter") == res["ref"]["counter"], f"{res['app'].get('counter')} vs {res['ref']['counter']}"))
    finish(a.out, checks)


if __name__ == "__main__":
    main()
