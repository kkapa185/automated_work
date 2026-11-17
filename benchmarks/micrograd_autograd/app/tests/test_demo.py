import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_r14_moons_deterministic_and_balanced():
    sys.path.insert(0, ROOT)
    import demo
    X1, y1 = demo.make_moons(100)
    X2, y2 = demo.make_moons(100)
    assert X1 == X2 and y1 == y2
    assert len(X1) == 100 and y1.count(1) == 50 and y1.count(-1) == 50


def test_r14_demo_script_reaches_95pct():
    r = subprocess.run([sys.executable, os.path.join(ROOT, "demo.py")],
                       capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0, r.stdout + r.stderr
    lines = [l for l in r.stdout.splitlines() if l.startswith("step")]
    assert len(lines) == 50 and "loss" in lines[0] and "accuracy" in lines[0]
    final = r.stdout.strip().splitlines()[-1]
    assert float(final.split("accuracy")[1].strip().rstrip("%")) >= 95.0
