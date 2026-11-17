import math
import random

import pytest

from micrograd.engine import Value


def test_r1_initial_state():
    v = Value(3.0)
    assert v.data == 3.0 and v.grad == 0


def test_r2_arithmetic_with_numbers():
    a = Value(4.0)
    assert (a + 1).data == 5 and (1 + a).data == 5
    assert (a - 1).data == 3 and (10 - a).data == 6
    assert (a * 2).data == 8 and (2 * a).data == 8
    assert (a / 2).data == 2 and (8 / a).data == 2
    assert (-a).data == -4
    assert (a ** 2).data == 16 and (a ** 0.5).data == 2


def test_r2_gradients_simple():
    a, b = Value(-4.0), Value(2.0)
    c = a + b
    d = a * b + b ** 3
    c = c + c + 1
    c = c + 1 + c + (-a)
    d = d + d * 2 + (b + a).relu()
    d = d + 3 * d + (b - a).relu()
    e = c - d
    f = e ** 2
    g = f / 2.0
    g = g + 10.0 / f
    g.backward()
    assert g.data == pytest.approx(24.7040816326530)
    assert a.grad == pytest.approx(138.8338192419825)
    assert b.grad == pytest.approx(645.5772594752186)


@pytest.mark.parametrize("bad", [Value(2.0), "2", None, [1]])
def test_r3_pow_rejects_non_numbers(bad):
    with pytest.raises(AssertionError):
        Value(2.0) ** bad


def test_r4_relu():
    for x, g in [(2.0, 1), (-2.0, 0), (0.0, 0)]:
        v = Value(x)
        out = v.relu()
        out.backward()
        assert out.data == max(0, x) and v.grad == g


def test_r5_accumulation_and_root_grad():
    a = Value(3.0)
    b = a + a
    b.backward()
    assert b.grad == 1 and a.grad == 2
    a = Value(3.0)
    c = a * a * a
    c.backward()
    assert a.grad == pytest.approx(27)


def test_r5_diamond_order():
    x = Value(2.0)
    y = x * 3
    z = x * 4
    out = y * z  # 12 x^2 -> 24x = 48
    out.backward()
    assert x.grad == pytest.approx(48)


def test_r6_repr():
    v = Value(2.5)
    assert repr(v) == "Value(data=2.5, grad=0)"
    (v * 2).backward()
    assert repr(v) == "Value(data=2.5, grad=2.0)" or repr(v) == "Value(data=2.5, grad=2)"


def _expr(xs):
    a, b, c = xs
    return ((a * b + c ** 2) / (b * b + 2.0) - a).relu() + (c - a * 0.5) ** 3 + 1 / (b * b + 1)


def test_r7_finite_differences():
    rng = random.Random(0)
    for _ in range(20):
        pts = [rng.uniform(-2, 2) for _ in range(3)]
        vs = [Value(p) for p in pts]
        out = _expr(vs)
        out.backward()
        h = 1e-6
        for i in range(3):
            hi = pts[:]; hi[i] += h
            lo = pts[:]; lo[i] -= h
            num = (_expr([Value(x) for x in hi]).data - _expr([Value(x) for x in lo]).data) / (2 * h)
            assert vs[i].grad == pytest.approx(num, rel=1e-4, abs=1e-4)


def test_r7_against_torch():
    torch = pytest.importorskip("torch")
    rng = random.Random(1)
    for _ in range(10):
        pts = [rng.uniform(-2, 2) for _ in range(3)]
        vs = [Value(p) for p in pts]
        out = _expr(vs)
        out.backward()
        ts = [torch.tensor(p, dtype=torch.double, requires_grad=True) for p in pts]
        a, b, c = ts
        t = ((a * b + c ** 2) / (b * b + 2.0) - a).relu() + (c - a * 0.5) ** 3 + 1 / (b * b + 1)
        t.backward()
        assert out.data == pytest.approx(t.item())
        for v, tt in zip(vs, ts):
            assert v.grad == pytest.approx(tt.grad.item())


def test_r8_deep_chain_no_recursion_error():
    x = Value(1.0)
    y = x
    for _ in range(5000):
        y = y * 1.0001
    y.backward()
    assert x.grad == pytest.approx(1.0001 ** 5000)
    assert math.isfinite(x.grad)


def test_r3_pow_int_and_float_and_negative_gradients():
    x = Value(2.0)
    y = x ** -2 + x ** 1.5
    y.backward()
    assert x.grad == pytest.approx(-2 * 2.0 ** -3 + 1.5 * 2.0 ** 0.5)


def test_r2_reflected_ops_gradients():
    x = Value(4.0)
    y = 10 - x + 8 / x + 3 * x
    y.backward()
    assert x.grad == pytest.approx(-1 - 8 / 16 + 3)
