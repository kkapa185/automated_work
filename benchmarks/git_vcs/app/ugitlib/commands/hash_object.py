"""git hash-object"""
import os
import sys

from ..objects import hash_object
from ..util import Fatal, out, usage_error, unknown_opt_msg

USAGE = "git hash-object [-t <type>] [-w] [--path=<file> | --no-filters] [--stdin [--literally]] [--] <file>..."


def run(ctx, args):
    typ = "blob"
    write = False
    use_stdin = False
    stdin_paths = False
    files = []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--":
            files += args[i + 1:]
            break
        if a == "-t":
            i += 1
            if i >= len(args):
                usage_error("switch `t' requires a value", USAGE)
            typ = args[i]
        elif a == "-w":
            write = True
        elif a == "--stdin":
            use_stdin = True
        elif a == "--stdin-paths":
            stdin_paths = True
        elif a in ("--literally", "--no-filters") or a.startswith("--path"):
            if a == "--path":
                i += 1
        elif a.startswith("-") and a != "-":
            usage_error(unknown_opt_msg(a), USAGE)
        else:
            files.append(a)
        i += 1
    if typ not in ("blob", "commit", "tree", "tag"):
        raise Fatal("invalid object type \"%s\"" % typ)
    repo = ctx.try_repo()
    if write and repo is None:
        ctx.repo()  # raises the proper fatal error

    def handle(data):
        if write:
            sha = repo.odb.write(typ, data)
        else:
            sha = hash_object(typ, data)
        out(sha + "\n")

    if use_stdin:
        handle(sys.stdin.buffer.read())
    if stdin_paths:
        for line in sys.stdin.read().splitlines():
            handle(_read(line))
    for f in files:
        handle(_read(f))
    if not (use_stdin or stdin_paths or files):
        usage_error("no file given", USAGE) if False else None
        raise Fatal("%s" % USAGE, 129, prefix="usage: ")
    return 0


def _read(path):
    try:
        if os.path.islink(path):
            return os.fsencode(os.readlink(path))
        with open(path, "rb") as f:
            return f.read()
    except OSError as e:
        raise Fatal("could not open '%s' for reading: %s" % (path, e.strerror))
