"""Graphviz DOT export of a computation graph (no graphviz package needed)."""


def _trace(root):
    nodes, edges = [], []
    seen = set()
    stack = [root]
    while stack:
        v = stack.pop()
        if id(v) in seen:
            continue
        seen.add(id(v))
        nodes.append(v)
        for c in v._prev:
            edges.append((c, v))
            stack.append(c)
    return nodes, edges


def draw_dot(root, rankdir="LR"):
    """Return DOT source text for the graph ending at ``root``."""
    assert rankdir in ("LR", "TB")
    nodes, edges = _trace(root)
    lines = ["digraph {", f"  rankdir={rankdir};"]
    for n in nodes:
        uid = str(id(n))
        label = "{ data %.4f | grad %.4f }" % (n.data, n.grad)
        lines.append(f'  "{uid}" [label="{label}", shape=record];')
        if n._op:
            lines.append(f'  "{uid}{n._op}" [label="{n._op}"];')
            lines.append(f'  "{uid}{n._op}" -> "{uid}";')
    for a, b in edges:
        lines.append(f'  "{id(a)}" -> "{id(b)}{b._op}";')
    lines.append("}")
    return "\n".join(lines) + "\n"
