"""Train MLP(2,[16,16,1]) on a deterministic two-moons dataset (SVM loss + L2, SGD)."""
import math
import random

from micrograd.nn import MLP


def make_moons(n=100):
    """Two interleaving half circles, deterministic (no randomness)."""
    half = n // 2
    X, y = [], []
    for i in range(half):
        t = math.pi * i / (half - 1)
        # small deterministic wobble so points are not perfectly on the curve
        r = 1 + 0.05 * math.sin(7 * i)
        X.append([r * math.cos(t), r * math.sin(t)])
        y.append(-1)
        X.append([1 - r * math.cos(t), 0.5 - r * math.sin(t)])
        y.append(1)
    return X, y


def evaluate(model, X, y, alpha=1e-4):
    scores = [model(x) for x in X]
    losses = [(1 + -yi * s).relu() for yi, s in zip(y, scores)]
    data_loss = sum(losses) * (1.0 / len(losses))
    reg_loss = alpha * sum((p * p for p in model.parameters()), 0)
    acc = sum((yi > 0) == (s.data > 0) for yi, s in zip(y, scores)) / len(y)
    return data_loss + reg_loss, acc


def main(steps=50, seed=1337, verbose=True):
    random.seed(seed)
    X, y = make_moons(100)
    model = MLP(2, [16, 16, 1])
    acc = 0.0
    for k in range(steps):
        loss, acc = evaluate(model, X, y)
        model.zero_grad()
        loss.backward()
        lr = 1.0 - 0.9 * k / steps
        for p in model.parameters():
            p.data -= lr * p.grad
        if verbose:
            print(f"step {k} loss {loss.data:.6f}, accuracy {acc * 100:.1f}%")
    loss, acc = evaluate(model, X, y)
    if verbose:
        print(f"final loss {loss.data:.6f}, accuracy {acc * 100:.1f}%")
    return acc


if __name__ == "__main__":
    final = main()
    raise SystemExit(0 if final >= 0.95 else 1)
