"""Oniguruma-flavoured regex support on top of Python's re."""
import re
from .values import JQError, typename

POSIX = {
    "alnum": "a-zA-Z0-9", "alpha": "a-zA-Z", "ascii": "\\x00-\\x7f", "blank": " \\t",
    "cntrl": "\\x00-\\x1f\\x7f", "digit": "0-9", "graph": "\\x21-\\x7e", "lower": "a-z",
    "print": "\\x20-\\x7e", "punct": "!-/:-@\\[-`{-~", "space": " \\t\\n\\r\\f\\v",
    "upper": "A-Z", "xdigit": "0-9a-fA-F", "word": "\\w",
}
PROPS = {
    "alpha": "[^\\W\\d_]", "digit": "\\d", "alnum": "[^\\W_]", "upper": "[A-Z]", "lower": "[a-z]",
    "space": "\\s", "word": "\\w", "punct": "[!-/:-@\\[-`{-~]", "xdigit": "[0-9a-fA-F]",
    "l": "[^\\W\\d_]", "lu": "[A-Z]", "ll": "[a-z]", "n": "\\d", "nd": "\\d", "p": "[!-/:-@\\[-`{-~]",
    "letter": "[^\\W\\d_]",
}
_cache = {}


def translate(pat):
    out = []
    i, n = 0, len(pat)
    stack = []      # per open group: number of scoped-flag wrappers to close
    pending = 0     # scoped wrappers opened at current level
    in_class = 0
    while i < n:
        c = pat[i]
        if c == "\\":
            if i + 1 >= n:
                raise JQError("%s (at offset 0) is not a valid regex: end pattern at escape" % pat)
            d = pat[i + 1]
            if d == "h":
                out.append("0-9a-fA-F" if in_class else "[0-9a-fA-F]")
            elif d == "H":
                out.append("[^0-9a-fA-F]")
            elif d == "z" and not in_class:
                out.append("\\Z")
            elif d == "Z" and not in_class:
                out.append("(?=\\n?\\Z)")
            elif d == "G" and not in_class:
                out.append("")
            elif d in "pP" and i + 2 < n and pat[i + 2] == "{":
                j = pat.index("}", i)
                name = pat[i + 3:j]
                neg = d == "P"
                if name.startswith("^"):
                    neg = not neg
                    name = name[1:]
                cls = PROPS.get(name.lower())
                if cls is None:
                    raise JQError("%s (at offset 0) is not a valid regex: invalid character property name {%s}" % (pat, name))
                if neg:
                    cls = "[^" + cls[1:] if cls.startswith("[") and not cls.startswith("[^") else (
                        "[" + cls[2:] if cls.startswith("[^") else "[^" + cls + "]")
                out.append(cls)
                i = j + 1
                continue
            else:
                out.append(c + d)
            i += 2
            continue
        if in_class:
            if c == "[" and pat.startswith("[:", i):
                j = pat.find(":]", i)
                if j > 0:
                    nm = pat[i + 2:j]
                    neg = nm.startswith("^")
                    if neg:
                        nm = nm[1:]
                    if nm in POSIX and not neg:
                        out.append(POSIX[nm])
                        i = j + 2
                        continue
            if c == "[":
                out.append("\\[")
                i += 1
                continue
            if c == "]":
                in_class = 0
                out.append("]")
                i += 1
                continue
            if c == "&" and pat.startswith("&&", i):
                out.append("&&")
                i += 2
                continue
            out.append(c)
            i += 1
            continue
        if c == "[":
            in_class = 1
            out.append("[")
            i += 1
            if i < n and pat[i] == "^":
                out.append("^")
                i += 1
            if i < n and pat[i] == "]":
                out.append("\\]")
                i += 1
            continue
        if c == "(":
            if pat.startswith("(?<", i) and i + 3 < n and pat[i + 3] not in "=!":
                out.append("(?P<")
                i += 3
                stack.append(pending)
                pending = 0
                continue
            m = re.compile(r"\(\?([imsx]*)(?:-([imsx]*))?\)").match(pat, i)
            if m and (m.group(1) or m.group(2)):
                on, off = m.group(1) or "", m.group(2) or ""
                out.append("(?%s%s:" % (on, "-" + off if off else ""))
                pending += 1
                i = m.end()
                continue
            if pat.startswith("(?#", i):
                j = pat.find(")", i)
                i = j + 1
                continue
            stack.append(pending)
            pending = 0
            out.append("(")
            i += 1
            continue
        if c == ")":
            out.append(")" * pending)
            pending = stack.pop() if stack else 0
            out.append(")")
            i += 1
            continue
        out.append(c)
        i += 1
    out.append(")" * pending)
    return "".join(out)


def compile_regex(pat, flags):
    key = (pat, flags)
    if key in _cache:
        return _cache[key]
    f = 0
    glob = False
    noempty = False
    single = False
    if flags is not None:
        if not isinstance(flags, str):
            raise JQError("%s (%s) is not a string" % (typename(flags), _dump(flags)))
        for ch in flags:
            if ch == "g":
                glob = True
            elif ch == "i":
                f |= re.IGNORECASE
            elif ch == "x":
                f |= re.VERBOSE
            elif ch == "m":
                f |= re.DOTALL
            elif ch == "s":
                single = True
            elif ch == "p":
                f |= re.DOTALL
                single = True
            elif ch == "n":
                noempty = True
            elif ch == "l":
                pass
            else:
                raise JQError("%s is not a valid modifier string" % flags)
    try:
        # Oniguruma's default (Perl_NT syntax): '^' is a line anchor, '$' ends the string
        rx = re.compile(translate(pat), f)
    except re.error as e:
        raise JQError("%s (at offset 0) is not a valid regex: %s" % (pat, e))
    except (ValueError, IndexError):
        raise JQError("%s (at offset 0) is not a valid regex" % pat)
    res = (rx, glob, noempty)
    if len(_cache) > 500:
        _cache.clear()
    _cache[key] = res
    return res


def _dump(v):
    from .interp import dump_trunc
    return dump_trunc(v)


def split_args(re_arg, flags):
    """Handle the [regex, flags] array form."""
    if isinstance(re_arg, list):
        if len(re_arg) > 2 or not re_arg:
            raise JQError("%s (%s) cannot be matched, as it is not a string" % (typename(re_arg), _dump(re_arg)))
        r = re_arg[0]
        fl = re_arg[1] if len(re_arg) > 1 else None
        return r, fl
    return re_arg, flags


def do_match(s, re_arg, flags, force_global=False):
    re_arg, flags = split_args(re_arg, flags)
    if not isinstance(s, str):
        raise JQError("%s (%s) cannot be matched, as it is not a string" % (typename(s), _dump(s)))
    if not isinstance(re_arg, str):
        raise JQError("%s (%s) cannot be matched, as it is not a string" % (typename(re_arg), _dump(re_arg)))
    rx, glob, noempty = compile_regex(re_arg, flags)
    glob = glob or force_global
    names = {v: k for k, v in rx.groupindex.items()}
    out = []
    it = rx.finditer(s) if glob else iter([m for m in [rx.search(s)] if m])
    for m in it:
        if noempty and m.end() == m.start():
            continue
        caps = []
        for gi in range(1, rx.groups + 1):
            st = m.start(gi)
            if st < 0:
                caps.append({"offset": -1, "length": 0, "string": None, "name": names.get(gi)})
            else:
                caps.append({"offset": st, "length": m.end(gi) - st, "string": m.group(gi),
                             "name": names.get(gi)})
        out.append({"offset": m.start(), "length": m.end() - m.start(), "string": m.group(),
                    "captures": caps})
    return out


def capture_obj(m):
    return {c["name"]: c["string"] for c in m["captures"] if c["name"] is not None}


def do_test(s, re_arg, flags=None):
    re_arg, flags = split_args(re_arg, flags)
    if not isinstance(s, str):
        raise JQError("%s (%s) cannot be matched, as it is not a string" % (typename(s), _dump(s)))
    if not isinstance(re_arg, str):
        raise JQError("%s (%s) cannot be matched, as it is not a string" % (typename(re_arg), _dump(re_arg)))
    rx, glob, noempty = compile_regex(re_arg, flags)
    if noempty:
        return any(m.end() > m.start() for m in rx.finditer(s))
    return rx.search(s) is not None


def do_split(s, re_arg, flags):
    if not isinstance(s, str):
        raise JQError("%s (%s) cannot be matched, as it is not a string" % (typename(s), _dump(s)))
    res = []
    prev = 0
    for m in do_match(s, re_arg, "g" + (flags or "") if True else flags):
        res.append(s[prev:m["offset"]])
        prev = m["offset"] + m["length"]
    res.append(s[prev:])
    return res
