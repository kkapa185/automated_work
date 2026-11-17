import numpy as np
import pytest

from btcpredict_lib import models as M
from btcpredict_lib.data import DataError


@pytest.mark.parametrize("name", M.NN_MODELS)
def test_r6_shapes_default(name):
    net = M.build_keras_model(name, 256, 16)
    out = net.predict(np.zeros((3, 256, 1), "float32"), verbose=0)
    assert out.shape == (3, 16)


def test_r6_cnn_spec_layers():
    net = M.build_keras_model("cnn", 256, 16)
    convs = [l for l in net.layers if l.__class__.__name__ == "Conv1D"]
    assert (convs[0].filters, convs[0].kernel_size, convs[0].strides) == (8, (20,), (3,))
    assert (convs[1].filters, convs[1].kernel_size, convs[1].strides) == (1, (16,), (4,))
    drop = [l for l in net.layers if l.__class__.__name__ == "Dropout"][0]
    assert drop.rate == 0.5


@pytest.mark.parametrize("name,i,o", [("cnn", 64, 4), ("cnn", 100, 10), ("lstm", 30, 5), ("gru", 30, 7)])
def test_r6_shapes_other(name, i, o):
    net = M.build_keras_model(name, i, o)
    assert net.predict(np.zeros((2, i, 1), "float32"), verbose=0).shape == (2, o)


def test_r6_cnn_too_short():
    with pytest.raises(DataError):
        M.build_keras_model("cnn", 10, 2)


def test_r6_gru_relu_nonnegative_lstm_leaky():
    g = M.build_keras_model("gru", 30, 4)
    assert (g.predict(np.random.rand(5, 30, 1).astype("float32"), verbose=0) >= 0).all()


def test_r7_lag():
    X = np.arange(10.0).reshape(1, 10, 1)
    assert list(M.LagBaseline(3).predict(X)[0]) == [7, 8, 9]
    with pytest.raises(DataError):
        M.LagBaseline(11).predict(X)


def test_r7_linear_recovers_linear_series():
    from btcpredict_lib.data import make_windows
    s = 0.5 + 0.01 * np.arange(200.0)
    X, y = make_windows(s, 8, 3, 1)
    m = M.LinearBaseline().fit(X[:100], y[:100])
    assert np.allclose(m.predict(X[100:]), y[100:], atol=1e-8)


def test_r7_linear_underdetermined_ok():
    X = np.random.rand(3, 20, 1)
    y = np.random.rand(3, 2)
    m = M.LinearBaseline().fit(X, y)
    assert np.allclose(m.predict(X), y, atol=1e-8)
