# ML-12: Minimal scalar autograd engine and neural-network library (`micrograd` API)

Build a small, dependency-free Python package `micrograd` for teaching backpropagation. It must be a
drop-in implementation of the well-known micrograd API so existing notebooks keep working:

* `micrograd.engine.Value(data)` — a scalar node with `.data`, `.grad` (initially 0), and the
  operators `+ - * /` (with Python numbers on either side), `**` (int/float exponent only), unary `-`,
  and `.relu()`. `v.backward()` sets `v.grad = 1` and back-propagates gradients to every node of the
  graph in reverse topological order, accumulating (`+=`) gradients for nodes used more than once.
  `repr(v)` is `Value(data=<data>, grad=<grad>)`.
* `micrograd.nn`: `Module` (`zero_grad()`, `parameters()`), `Neuron(nin, nonlin=True)` (weights
  `Value(random.uniform(-1, 1))` drawn in input order using Python's global `random` module, then bias
  `Value(0)`; output `relu(w·x + b)` if `nonlin` else linear), `Layer(nin, nout, **kwargs)`,
  `MLP(nin, nouts)` (all layers non-linear except the last). `parameters()` order: for each layer, for each
  neuron, its weights then its bias. A layer with a single neuron returns a scalar `Value`, otherwise a list.
  `repr` of the modules: `ReLUNeuron(3)` / `LinearNeuron(3)`, `Layer of [...]`, `MLP of [...]`.
* A `demo.py` that trains an `MLP(2, [16, 16, 1])` binary classifier with SVM max-margin loss + L2
  regularisation and SGD on a deterministic two-moons style dataset (generated in code, no downloads),
  printing loss and accuracy per step and reaching >= 95% training accuracy.
* An optional `draw_dot(root)` helper producing Graphviz source text for a computation graph.

Packaging: a `setup.py` or `pyproject.toml` so `pip install -e .` works, plus a test-suite that checks
gradients against finite differences (and, where available, against PyTorch).
