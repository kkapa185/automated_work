"""Module system: import / include directives, -L search paths and modulemeta."""
import os

from .values import JQError, iter_values, ParseError
from .lexer import JQSyntaxError
from .parser import parse

DEFAULT_SEARCH = ["~/.jq", "$ORIGIN/../lib/jq", "$ORIGIN/../lib"]


def _expand(path, origin_dir, rel_dir):
    if path.startswith("~/"):
        return os.path.join(os.path.expanduser("~"), path[2:])
    if path.startswith("$ORIGIN/"):
        return os.path.join(origin_dir, path[len("$ORIGIN/"):])
    if path == "." or path.startswith("./") or path.startswith("../"):
        return os.path.join(rel_dir, path)
    return path


def _meta_value(node):
    """Evaluate a constant metadata object literal."""
    if node is None:
        return None
    from .interp import Compiler
    from .builtins import BUILTINS
    fn = Compiler(BUILTINS).compile(node, None)
    for _, v in fn(None, None, None):
        return v
    return None


def _search_dirs(meta, lib_dirs, rel_dir):
    origin = os.path.dirname(os.path.realpath(__file__ + "/../../jq"))
    dirs = []
    m = _meta_value(meta) if meta is not None else None
    if isinstance(m, dict) and "search" in m:
        s = m["search"]
        for d in ([s] if isinstance(s, str) else s):
            dirs.append(_expand(d, origin, rel_dir) if not os.path.isabs(d) else d)
            if not os.path.isabs(d) and not (d.startswith("./") or d == "." or d.startswith("../")):
                dirs[-1] = os.path.join(rel_dir, d)
    base = lib_dirs if lib_dirs else DEFAULT_SEARCH
    for d in base:
        if d is None or d == "":
            break
        dirs.append(_expand(d, origin, rel_dir))
    return dirs


def find_module(relpath, ext, meta, lib_dirs, rel_dir):
    parts = relpath.split("/")
    if len(parts) >= 2 and parts[-1] == parts[-2]:
        raise JQError("module names must not have equal consecutive components: %s" % relpath)
    for d in _search_dirs(meta, lib_dirs, rel_dir):
        for cand in (os.path.join(d, relpath + ext), os.path.join(d, relpath, parts[-1] + ext)):
            if os.path.isfile(cand):
                return cand
    raise JQError("module not found: %s (searched in %s)" % (
        relpath, ", ".join(_search_dirs(meta, lib_dirs, rel_dir))))


def _defs_of(body):
    defs = []
    node = body
    while node[0] == "funcdef":
        defs.append(node)
        node = node[4]
    return defs, node


def _load_defs(path, lib_dirs, seen):
    """Return list of funcdef nodes (without continuation) for a module file."""
    if path in seen:
        raise JQError("circular module import: %s" % path)
    with open(path, "rb") as fh:
        text = fh.read().decode("utf-8", "replace")
    try:
        mod, directives, body = parse(text)
    except JQSyntaxError as e:
        raise JQError("%s: %s" % (path, e.msg))
    defs, _ = _defs_of(body)
    rel_dir = os.path.dirname(os.path.abspath(path))
    pre, post = expand_directives(directives, lib_dirs, rel_dir, seen | {path})
    return pre + defs, post


def expand_directives(directives, lib_dirs, rel_dir, seen):
    """Returns (def nodes to prepend, list of (data_name, value) bindings)."""
    defs_out = []
    data = []
    for kind, relpath, alias, meta in directives:
        if kind == "import" and alias and alias.startswith("$"):
            path = find_module(relpath, ".json", meta, lib_dirs, rel_dir)
            with open(path, "rb") as fh:
                vals = [v for v, _ in iter_values(fh.read().decode("utf-8", "replace"))]
            name = alias[1:]
            data.append((name + "::" + name, vals))
            data.append((name, vals))
            continue
        path = find_module(relpath, ".jq", meta, lib_dirs, rel_dir)
        mdefs, mdata = _load_defs(path, lib_dirs, seen)
        data.extend(mdata)
        defs_out.extend(mdefs)
        if kind == "import":
            for d in mdefs:
                _, name, params, _, _ = d
                call_args = [("var", p[1:]) if p.startswith("$") else ("call", p, []) for p in params]
                defs_out.append(("funcdef", "%s::%s" % (alias, name), params,
                                 ("call", name, call_args), None))
    return defs_out, data


def load_directives(directives, body, opts, comp):
    rel_dir = os.getcwd()
    try:
        defs, data = expand_directives(directives, opts.lib_dirs, rel_dir, frozenset())
    except OSError as e:
        raise JQError("module error: %s" % e)
    node = body
    for name, vals in reversed(data):
        node = ("bind", ("lit", vals), [("pvar", name)], node)
    for d in reversed(defs):
        node = ("funcdef", d[1], d[2], d[3], node)
    return node


def module_meta(name, state):
    rel_dir = os.getcwd()
    path = find_module(name, ".jq", None, state.lib_dirs, rel_dir)
    with open(path, "rb") as fh:
        text = fh.read().decode("utf-8", "replace")
    mod, directives, body = parse(text)
    res = _meta_value(mod) or {}
    if not isinstance(res, dict):
        res = {}
    res = dict(res)
    deps = []
    for kind, relpath, alias, meta in directives:
        d = {}
        m = _meta_value(meta) if meta is not None else None
        if isinstance(m, dict):
            d.update(m)
        if alias:
            d["as"] = alias.lstrip("$")
        d["is_data"] = bool(alias and alias.startswith("$"))
        d["relpath"] = relpath
        deps.append(d)
    res["deps"] = deps
    defs, _ = _defs_of(body)
    res["defs"] = ["%s/%d" % (d[1], len(d[2])) for d in defs]
    return res
