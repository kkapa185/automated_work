# Benchmark report — karpathy/micrograd

**Ticket:** [`task.md`](task.md) (ML-12). It asks for a scalar autograd engine and an MLP library that is
API-compatible with micrograd, plus a `demo.py` training script.

**Reference execution:** the hidden harness [`compare.py`](compare.py) runs one driver against both packages:
- 200 random computation graphs of 25 operations each (`+ - * / **`, relu, reflected ops), comparing the
  forward values and every leaf gradient;
- a seeded `MLP(3,[4,4,1])`, comparing its parameter init and a 20-step SGD training trajectory;
- the module `repr`s and the scalar return from a single-neuron layer;
- `demo.py`, which must reach at least 95% accuracy.

## Result (attempt 1): score 1.00 (7/7)
Everything is identical to the reference to 1e-9. The seeded initialization and the training losses
match exactly, which requires the same `random` consumption order. `demo.py` trains the two-moons
classifier past 95%.

**Process:** 4 turns on one session: plan → implement → review (GAPS_FIXED) → review (PASS). $0.44.
The 5.5 h wall time includes the 2 h 48 min automatic usage-limit pause and the worker restart; the task
resumed on its original session.
