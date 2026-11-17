# Requirements: micrograd (scalar autograd + tiny NN library)

## Product
A dependency-free Python library `micrograd` (library classification) providing a scalar reverse-mode
autograd `Value`, a small `nn` module (Module/Neuron/Layer/MLP), an optional Graphviz `draw_dot`,
a deterministic `demo.py` training an MLP on a two-moons dataset, packaging via pyproject.toml, and a pytest suite.

## Acceptance criteria
R1. `Value(data)` has `.data`, `.grad == 0` initially.
R2. `+ - * /` work between Values and with Python numbers on either side (radd, rsub, rmul, rtruediv); unary `-`.
R3. `**` accepts int/float exponent only; other types (Value, str) raise AssertionError/TypeError-class error (assert).
R4. `.relu()` returns max(0,x); gradient 1 if out>0 else 0.
R5. `backward()` sets root.grad=1, traverses in reverse topological order, accumulates (+=) for reused nodes (e.g. a+a, a*a).
R6. `repr(v) == "Value(data=<data>, grad=<grad>)"`.
R7. Gradients match central finite differences on random expressions; match PyTorch if installed (skip otherwise).
R8. Deep graphs (e.g. 5000-long chain) do not hit recursion limit (iterative topo sort).
R9. `nn.Module.zero_grad()` zeroes all parameter grads; `parameters()` returns [] by default.
R10. `Neuron(nin, nonlin=True)`: weights `Value(random.uniform(-1,1))` in input order via global `random`, then bias Value(0); output relu(w·x+b) or linear. repr `ReLUNeuron(n)`/`LinearNeuron(n)`.
R11. `Layer(nin,nout,**kwargs)`: single neuron returns scalar Value, else list. repr `Layer of [..]` (comma-joined neuron reprs).
R12. `MLP(nin,nouts)`: all layers nonlinear except last. repr `MLP of [..]`. parameters order: layer, neuron, weights then bias.
R13. Seeding `random.seed(s)` reproduces identical parameters; construction consumes exactly nin draws per neuron.
R14. `demo.py` trains MLP(2,[16,16,1]) with SVM max-margin loss + L2 reg + SGD on deterministic in-code two-moons data; prints loss and accuracy per step; reaches >=95% train accuracy; exit code 0; deterministic.
R15. `draw_dot(root)` returns Graphviz DOT source text (no graphviz dependency) with nodes for values and ops and edges.
R16. `pip install -e .` works (pyproject.toml); no runtime dependencies. README documents install/run/test.

## Assumptions
- Python >=3.8. Value keeps `_prev` set, `_op` string, `_backward` closure.
- Invalid `**` exponent raises AssertionError (matches "int/float only" assert style).
- Moons data uses math only (no random) or a locally seeded generator.
- Neuron weight draw uses global `random`; demo seeds it.

## Test strategy
- tests/test_engine.py: R1-R8 (unit, finite diff, optional torch via importorskip, deep chain).
- tests/test_nn.py: R9-R13 (seeded order, repr, parameters, zero_grad, training reduces loss).
- tests/test_demo.py: R14 by running demo main (subprocess) and checking accuracy.
- tests/test_viz.py: R15.
