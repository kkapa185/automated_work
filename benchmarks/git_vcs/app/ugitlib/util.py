"""Shared helpers: errors, output, path encoding."""
import sys


class Fatal(Exception):
    """A fatal error: printed as ``fatal: <msg>`` (or raw) and exit with ``code``."""

    def __init__(self, msg, code=128, prefix="fatal: "):
        super().__init__(msg)
        self.msg = msg
        self.code = code
        self.prefix = prefix


class Exit(Exception):
    """Terminate with an exit code without printing anything."""

    def __init__(self, code=0):
        super().__init__(code)
        self.code = code


def usage_error(msg, usage=None):
    text = "error: %s\n" % msg
    if usage:
        text += "usage: %s\n" % usage
    raise Fatal(text.rstrip("\n"), 129, prefix="")


def fsdecode(b):
    return b.decode("utf-8", "surrogateescape")


def fsencode(s):
    return s.encode("utf-8", "surrogateescape")


def out(data):
    if isinstance(data, str):
        data = fsencode(data)
    sys.stdout.buffer.write(data)


def err(data):
    if isinstance(data, str):
        data = fsencode(data)
    sys.stdout.buffer.flush()
    sys.stderr.buffer.write(data)
    sys.stderr.buffer.flush()


def quote_path(name):
    """C-style quoting of unusual path names (core.quotepath=true)."""
    raw = fsencode(name)
    need = False
    res = []
    esc = {7: "\\a", 8: "\\b", 9: "\\t", 10: "\\n", 11: "\\v", 12: "\\f", 13: "\\r",
           34: '\\"', 92: "\\\\"}
    for c in raw:
        if c in esc:
            need = True
            res.append(esc[c])
        elif c < 0x20 or c == 0x7f or c >= 0x80:
            need = True
            res.append("\\%03o" % c)
        else:
            res.append(chr(c))
    if need:
        return '"' + "".join(res) + '"'
    return name


def path_key(name):
    return fsencode(name)


def expand_short(args, flags, valued=""):
    """Expand bundled short options (``-am msg`` -> ``-a -m msg``)."""
    res = []
    skip = False
    for idx, a in enumerate(args):
        if skip:
            res.append(a)
            skip = False
            continue
        if a == "--":
            res.extend(args[idx:])
            break
        if (a.startswith("-") and not a.startswith("--") and len(a) > 2
                and all(c in flags + valued for c in a[1:])):
            letters = a[1:]
            for j, c in enumerate(letters):
                res.append("-" + c)
                if c in valued:
                    rest = letters[j + 1:]
                    if rest:
                        res.append(rest)
                    else:
                        skip = True
                    break
            continue
        res.append(a)
        if a.startswith("-") and not a.startswith("--") and len(a) == 2 and a[1] in valued:
            skip = True
    return res


def unknown_opt_msg(arg):
    """git's wording: long options are 'unknown option `name'', short ones 'unknown switch `c''."""
    if arg.startswith("--"):
        return "unknown option `%s'" % arg[2:].split("=", 1)[0]
    return "unknown switch `%s'" % arg[1:2]
