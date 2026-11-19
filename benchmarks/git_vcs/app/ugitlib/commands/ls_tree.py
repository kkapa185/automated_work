"""git ls-tree"""
import posixpath

from ..objects import ObjectNotFound, mode_type
from ..pathspec import normalize_path
from ..repo import BadRevision
from ..util import Fatal, out, quote_path, usage_error, unknown_opt_msg

USAGE = "git ls-tree [<options>] <tree-ish> [<path>...]"


def run(ctx, args):
    recurse = show_trees = only_trees = long_ = zero = name_only = full_name = full_tree = False
    abbrev = None
    pos = []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--":
            pos += args[i + 1:]
            break
        if a == "-r":
            recurse = True
        elif a == "-t":
            show_trees = True
        elif a == "-d":
            only_trees = True
        elif a in ("-l", "--long"):
            long_ = True
        elif a == "-z":
            zero = True
        elif a in ("--name-only", "--name-status"):
            name_only = True
        elif a == "--full-name":
            full_name = True
        elif a == "--full-tree":
            full_tree = True
        elif a == "--abbrev":
            abbrev = 7
        elif a.startswith("--abbrev="):
            abbrev = int(a.split("=", 1)[1])
        elif a.startswith("-") and a != "-":
            usage_error(unknown_opt_msg(a), USAGE)
        else:
            pos.append(a)
        i += 1
    if not pos:
        raise Fatal(USAGE, 129, prefix="usage: ")
    repo = ctx.repo()
    name = pos[0]
    try:
        sha = repo.resolve(name)
        obj_type = repo.odb.read(sha)[0]
    except (BadRevision, ObjectNotFound):
        raise Fatal("Not a valid object name %s" % name)
    try:
        sha = repo.peel(sha, "tree")
    except (BadRevision, ObjectNotFound):
        raise Fatal("not a tree object")
    del obj_type
    prefix = "" if (full_tree or repo.worktree is None) else repo.prefix
    pats = []
    for p in pos[1:]:
        trailing = p.endswith("/")
        np_ = normalize_path(repo, p, top=full_tree) if repo.worktree is not None else p.strip("/")
        pats.append((np_, trailing))
    if not pats and prefix:
        pats = [(prefix.rstrip("/"), True)]
    term = "\0" if zero else "\n"

    def display(path):
        if full_name or not prefix:
            return path
        return posixpath.relpath(path, prefix.rstrip("/"))

    def emit(mode, esha, path):
        if only_trees and mode != 0o40000:
            return
        shown = display(path)
        shown = shown if zero else quote_path(shown)
        if name_only:
            out(shown + term)
            return
        sh = esha[:abbrev] if abbrev else esha
        if long_:
            if mode == 0o40000 or mode == 0o160000:
                size = "-"
            else:
                size = str(len(repo.odb.read(esha)[1]))
            out("%06o %s %s %7s\t%s%s" % (mode, mode_type(mode), sh, size, shown, term))
        else:
            out("%06o %s %s\t%s%s" % (mode, mode_type(mode), sh, shown, term))

    def walk(tree_sha, base, inside):
        for mode, ename, esha in repo.read_tree(tree_sha):
            path = base + ename
            exact_slash = way = False
            if pats and not inside:
                exact_plain = any(pt == path and not tr for pt, tr in pats)
                exact_slash = any(pt == path and tr for pt, tr in pats)
                under = any(pt == "" or path.startswith(pt + "/") for pt, _ in pats)
                way = any(pt.startswith(path + "/") for pt, _ in pats)
                if not (exact_plain or exact_slash or under or way):
                    continue
                sel = exact_plain or under
            else:
                sel = True
            if mode != 0o40000:
                if sel:
                    emit(mode, esha, path)
                continue
            if recurse or only_trees and recurse:
                if (show_trees or only_trees) and (sel or way):
                    emit(mode, esha, path)
                if sel or way or exact_slash:
                    walk(esha, path + "/", inside or sel or exact_slash)
            else:
                if sel and not exact_slash:
                    emit(mode, esha, path)
                if way or exact_slash:
                    walk(esha, path + "/", inside or exact_slash)

    walk(sha, "", False)
    return 0
