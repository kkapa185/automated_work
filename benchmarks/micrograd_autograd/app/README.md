# micrograd

A small, dependency-free scalar autograd engine and neural-network library for teaching backpropagation.

* `micrograd.engine.Value` – scalar node supporting `+ - * /`, `**` (int/float), unary `-`, `relu()`, `backward()`.
  Backward uses an iterative topological sort (deep graphs are safe) and accumulates gradients with `+=`.
* `micrograd.nn` – `Module`, `Neuron`, `Layer`, `MLP`. Weights come from the global `random` module
  (`random.uniform(-1, 1)`, input order), bias starts at `Value(0)`.
* `micrograd.draw_dot(root)` – returns Graphviz DOT source text (no graphviz package required).
* `demo.py` – trains `MLP(2, [16, 16, 1])` on a deterministic in-code two-moons dataset with SVM max-margin
  loss + L2 regularisation and SGD; prints loss/accuracy each step (reaches 100% training accuracy, ~45 s).

## Install / run / test
```
pip install -e .[test]
python demo.py
python -m pytest
```
Tests check gradients against finite differences, and against PyTorch when installed (skipped otherwise).
No downloads are needed.
