"""Run identical random computation graphs and seeded MLPs through the reference and the generated micrograd."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common import check, finish, run, run_python_driver  # noqa: E402

DRIVER = r'''
import json, random, sys, math
from micrograd.engine import Value
from micrograd.nn import MLP, Neuron, Layer
cfg = json.loads(sys.stdin.read())
out = {"graphs": [], "mlp": [], "repr": []}
rng = random.Random(cfg["seed"])
for g in range(cfg["n_graphs"]):
    leaves = [Value(rng.uniform(-3, 3)) for _ in range(4)]
    nodes = list(leaves)
    for step in range(25):
        op = rng.choice(["add", "mul", "sub", "div", "pow", "relu", "neg", "radd", "rmul", "rsub", "rdiv"])
        a, b = rng.choice(nodes), rng.choice(nodes)
        c = rng.uniform(0.5, 2.0)
        try:
            if op == "add": n = a + b
            elif op == "mul": n = a * b
            elif op == "sub": n = a - b
            elif op == "div": n = a / (b * b + 1.0)
            elif op == "pow": n = (a * a + 0.5) ** rng.choice([2, 3, 0.5, -1])
            elif op == "relu": n = a.relu()
            elif op == "neg": n = -a
            elif op == "radd": n = c + a
            elif op == "rmul": n = c * a
            elif op == "rsub": n = c - a
            else: n = c / (a * a + 1.0)
        except Exception as e:
            n = a
        if abs(n.data) < 1e6:
            nodes.append(n)
    root = sum(nodes[-5:], Value(0.0)) if True else None
    root.backward()
    out["graphs"].append({"data": root.data, "grads": [l.grad for l in leaves]})
random.seed(cfg["seed"])
m = MLP(3, [4, 4, 1])
out["n_params"] = len(m.parameters())
out["params"] = [p.data for p in m.parameters()]
xs = [[2.0, 3.0, -1.0], [3.0, -1.0, 0.5], [0.5, 1.0, 1.0], [1.0, 1.0, -1.0]]
ys = [1.0, -1.0, -1.0, 1.0]
for step in range(20):
    pred = [m(x) for x in xs]
    loss = sum((yp - y) ** 2 for yp, y in zip(pred, ys))
    m.zero_grad()
    loss.backward()
    for p in m.parameters():
        p.data -= 0.05 * p.grad
    out["mlp"].append(loss.data)
out["repr"] = [repr(Value(2.0)), repr(Neuron(3)), repr(Neuron(2, nonlin=False)), repr(Layer(2, 1)), repr(MLP(2, [1]))]
out["layer1"] = type(Layer(2, 1)([1.0, 2.0])).__name__
print(json.dumps(out))
'''


def close(a, b, tol=1e-9):
    if isinstance(a, list):
        return isinstance(b, list) and len(a) == len(b) and all(close(x, y, tol) for x, y in zip(a, b))
    try:
        return abs(float(a) - float(b)) <= tol * max(1.0, abs(float(a)), abs(float(b)))
    except (TypeError, ValueError):
        return a == b


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", required=True)
    ap.add_argument("--reference", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    checks = []
    payload = {"seed": 1234, "n_graphs": 200}
    ref = run_python_driver(DRIVER, a.reference, a.reference, payload)
    got = run_python_driver(DRIVER, a.app, a.app, payload)
    checks.append(check("driver runs against generated package", "__error__" not in got, got.get("__error__", "")))
    if "__error__" not in got:
        gm = sum(close(x["data"], y["data"]) and close(x["grads"], y["grads"]) for x, y in zip(ref["graphs"], got["graphs"]))
        checks.append(check("random graphs: forward values and leaf gradients identical (200 graphs)", gm == len(ref["graphs"]), f"{gm}/{len(ref['graphs'])}"))
        checks.append(check("MLP parameter count and seeded init identical", got["n_params"] == ref["n_params"] and close(got["params"], ref["params"]), f"{got['n_params']} vs {ref['n_params']}"))
        checks.append(check("MLP training trajectory (20 SGD steps) identical", close(got["mlp"], ref["mlp"], 1e-7), f"final {got['mlp'][-1]} vs {ref['mlp'][-1]}"))
        checks.append(check("reprs match the micrograd API", got["repr"] == ref["repr"], f"{got['repr']} vs {ref['repr']}"))
        checks.append(check("single-neuron layer returns a scalar Value", got["layer1"] == ref["layer1"], got["layer1"]))
    demo = run([sys.executable, "demo.py"], cwd=a.app, timeout=900)
    import re
    accs = [float(x) for x in re.findall(r"acc(?:uracy)?\D{0,5}([01]?\.\d+|\d{1,3}(?:\.\d+)?%)".replace("%)", ")%?"), demo.stdout, re.I)] if demo.returncode == 0 else []
    accs = [x / 100 if x > 1 else x for x in accs]
    checks.append(check("demo.py trains to >= 95% accuracy", demo.returncode == 0 and accs and max(accs) >= 0.95, f"rc={demo.returncode} best={max(accs) if accs else None} {demo.stderr[-300:]}"))
    finish(a.out, checks)


if __name__ == "__main__":
    main()
