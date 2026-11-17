import random

import pytest

from micrograd.engine import Value
from micrograd.nn import MLP, Layer, Module, Neuron


def test_r9_module_defaults_and_zero_grad():
    assert Module().parameters() == []
    m = MLP(2, [3, 1])
    out = m([1.0, -2.0])
    out.backward()
    assert any(p.grad != 0 for p in m.parameters())
    m.zero_grad()
    assert all(p.grad == 0 for p in m.parameters())


def test_r10_neuron_init_order_and_forward():
    random.seed(42)
    n = Neuron(3)
    random.seed(42)
    expected = [random.uniform(-1, 1) for _ in range(3)]
    assert [w.data for w in n.w] == expected
    assert n.b.data == 0
    assert [p.data for p in n.parameters()] == expected + [0]
    x = [1.0, 2.0, 3.0]
    pre = sum(w * xi for w, xi in zip(expected, x))
    assert n(x).data == pytest.approx(max(0, pre))
    lin = Neuron(3, nonlin=False)
    out = lin([1, 1, 1])
    assert out.data == pytest.approx(sum(w.data for w in lin.w))
    assert isinstance(out, Value)


def test_r10_linear_can_be_negative():
    n = Neuron(1, nonlin=False)
    n.w[0].data = -1.0
    assert n([2.0]).data == -2.0
    n.nonlin = True
    assert n([2.0]).data == 0


def test_r10_repr():
    assert repr(Neuron(3)) == "ReLUNeuron(3)"
    assert repr(Neuron(3, nonlin=False)) == "LinearNeuron(3)"


def test_r11_layer():
    assert isinstance(Layer(2, 1)([1, 2]), Value)
    out = Layer(2, 3)([1, 2])
    assert isinstance(out, list) and len(out) == 3
    assert repr(Layer(2, 2)) == "Layer of [ReLUNeuron(2), ReLUNeuron(2)]"
    assert repr(Layer(2, 1, nonlin=False)) == "Layer of [LinearNeuron(2)]"
    assert len(Layer(4, 3).parameters()) == 15


def test_r12_mlp():
    m = MLP(2, [4, 4, 1])
    assert repr(m) == ("MLP of [Layer of [ReLUNeuron(2), ReLUNeuron(2), ReLUNeuron(2), ReLUNeuron(2)], "
                       "Layer of [ReLUNeuron(4), ReLUNeuron(4), ReLUNeuron(4), ReLUNeuron(4)], "
                       "Layer of [LinearNeuron(4)]]")
    assert len(m.parameters()) == 4 * 3 + 4 * 5 + 5
    assert isinstance(m([0.5, 0.5]), Value)
    assert isinstance(MLP(2, [3, 2])([1, 1]), list)


def test_r12_parameter_order():
    m = MLP(2, [2, 1])
    params = m.parameters()
    expect = []
    for layer in m.layers:
        for n in layer.neurons:
            expect += n.w + [n.b]
    assert all(a is b for a, b in zip(params, expect)) and len(params) == len(expect)


def test_r13_seed_reproducible_and_draw_count():
    random.seed(7)
    a = [p.data for p in MLP(2, [3, 1]).parameters()]
    random.seed(7)
    b = [p.data for p in MLP(2, [3, 1]).parameters()]
    assert a == b
    random.seed(7)
    MLP(2, [3, 1])
    after = random.random()
    random.seed(7)
    for _ in range(3 * 2 + 1 * 3):
        random.uniform(-1, 1)
    assert after == random.random()


def test_training_reduces_loss():
    random.seed(3)
    m = MLP(2, [4, 1])
    X = [[0, 0], [1, 1], [1, 0], [0, 1]]
    y = [-1, -1, 1, 1]

    def loss():
        return sum(((m(x) - t) ** 2 for x, t in zip(X, y)), 0)

    first = loss().data
    for _ in range(30):
        m.zero_grad()
        l = loss()
        l.backward()
        for p in m.parameters():
            p.data -= 0.02 * p.grad
    assert loss().data < first
