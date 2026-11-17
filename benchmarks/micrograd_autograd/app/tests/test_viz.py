from micrograd import Value, draw_dot


def test_r15_draw_dot():
    a, b = Value(2.0), Value(3.0)
    c = a * b + 1
    c.backward()
    dot = draw_dot(c)
    assert dot.startswith("digraph")
    assert dot.rstrip().endswith("}")
    assert "data 7.0000" in dot and "grad 1.0000" in dot
    assert '"*"' in dot.replace(f"{id(a)}", "") or "label=\"*\"" in dot
    assert dot.count("->") >= 6
