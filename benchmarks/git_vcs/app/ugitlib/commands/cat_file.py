"""git cat-file"""
import sys

from ..objects import ObjectNotFound, mode_type, parse_commit, parse_tag, parse_tree
from ..repo import BadRevision
from ..util import Fatal, out, quote_path, usage_error, fsencode, unknown_opt_msg

USAGE = "git cat-file (-t | -s | -e | -p | <type> | --textconv | --filters) [--path=<path>] <object>"


def format_tree(data):
    lines = []
    for mode, name, sha in parse_tree(data):
        lines.append("%06o %s %s\t%s\n" % (mode, mode_type(mode), sha, quote_path(name)))
    return "".join(lines).encode("utf-8", "surrogateescape")


def run(ctx, args):
    mode = None
    batch = None
    pos = []
    for a in args:
        if a in ("-t", "-s", "-e", "-p"):
            mode = a
        elif a == "--batch" or a.startswith("--batch="):
            batch = "full"
        elif a == "--batch-check" or a.startswith("--batch-check="):
            batch = "check"
        elif a.startswith("-") and a != "-":
            usage_error(unknown_opt_msg(a), USAGE)
        else:
            pos.append(a)
    repo = ctx.repo()
    if batch:
        return _batch(repo, batch)
    if mode is None:
        if len(pos) != 2:
            raise Fatal(USAGE, 129, prefix="usage: ")
        want, name = pos
    else:
        if len(pos) != 1:
            if not pos:
                raise Fatal("fatal: <object> required with '%s'\n\nusage: %s" % (mode, USAGE), 129, prefix="")
            raise Fatal(USAGE, 129, prefix="usage: ")
        want, name = None, pos[0]
    try:
        sha = repo.resolve(name)
    except BadRevision:
        if mode == "-e" and len(name) == 40 and all(c in "0123456789abcdefABCDEF" for c in name):
            return 1
        raise Fatal("Not a valid object name %s" % name)
    try:
        typ, data = repo.odb.read(sha)
    except ObjectNotFound:
        if mode == "-e":
            return 1
        raise Fatal("git cat-file: could not get object info")
    if mode == "-e":
        return 0
    if mode == "-t":
        out(typ + "\n")
    elif mode == "-s":
        out("%d\n" % len(data))
    elif mode == "-p":
        if typ == "tree":
            out(format_tree(data))
        else:
            out(data)
    else:
        if want != typ:
            try:
                sha2 = repo.peel(sha, want)
            except (BadRevision, ObjectNotFound):
                raise Fatal("git cat-file: could not get object info")
            typ, data = repo.odb.read(sha2)
        out(data)
    return 0


def _batch(repo, kind):
    for line in sys.stdin.read().splitlines():
        name = line.strip()
        try:
            sha = repo.resolve(name)
            typ, data = repo.odb.read(sha)
        except (BadRevision, ObjectNotFound):
            out("%s missing\n" % name)
            continue
        out("%s %s %d\n" % (sha, typ, len(data)))
        if kind == "full":
            out(data)
            out("\n")
    return 0
