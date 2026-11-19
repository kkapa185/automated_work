"""git log (and the commit rendering shared with git show)"""
import os

from .. import diff as D
from ..diffout import DiffOpts, emit, parse_option
from ..index import flatten_tree
from ..objects import EMPTY_TREE, ObjectNotFound, parse_tag
from ..pathspec import Pathspec
from ..pretty import Formatter, build_decorations, split_message
from ..repo import BadRevision
from ..revwalk import merge_bases, walk
from ..util import Fatal, out, usage_error
from .diff import bad_arg


class LogOpts:
    def __init__(self):
        self.fmt = "medium"          # medium|oneline|short|full|fuller|raw|user
        self.user_format = None
        self.terminator = True       # tformat vs format:
        self.date = "default"
        self.max_count = None
        self.skip = 0
        self.reverse = False
        self.first_parent = False
        self.merges = None           # None | True (only) | False (none)
        self.decorate = False
        self.abbrev = None
        self.all = False
        self.oneline_full = False
        self.diff = DiffOpts()


def parse_pretty(lo, value):
    if value in ("oneline",):
        lo.fmt = "oneline"
        lo.oneline_full = True
    elif value in ("medium", "short", "full", "fuller"):
        lo.fmt = value
    elif value.startswith("format:"):
        lo.fmt, lo.user_format, lo.terminator = "user", value[7:], False
    elif value.startswith("tformat:"):
        lo.fmt, lo.user_format, lo.terminator = "user", value[8:], True
    elif value == "":
        lo.fmt = "medium"
    elif "%" in value:
        lo.fmt, lo.user_format, lo.terminator = "user", value, True
    else:
        raise Fatal("invalid --pretty format: %s" % value)


def parse_common(lo, a, args, i):
    """Parse option ``a`` at args[i]; return new index or None if not an option we know."""
    if a == "--oneline":
        lo.fmt = "oneline"
        lo.oneline_full = False
        if lo.abbrev is None:
            lo.abbrev = 0
    elif a.startswith("--pretty=") or a.startswith("--format="):
        parse_pretty(lo, a.split("=", 1)[1])
    elif a in ("--pretty", ):
        lo.fmt = "medium"
    elif a.startswith("--date="):
        lo.date = a.split("=", 1)[1]
    elif a == "-n":
        if i + 1 >= len(args):
            usage_error("switch `n' requires a value")
        lo.max_count = int(args[i + 1])
        return i + 2
    elif a.startswith("-n") and a[2:].isdigit():
        lo.max_count = int(a[2:])
    elif a.startswith("--max-count="):
        lo.max_count = int(a.split("=", 1)[1])
    elif a.startswith("-") and a[1:].isdigit():
        lo.max_count = int(a[1:])
    elif a.startswith("--skip="):
        lo.skip = int(a.split("=", 1)[1])
    elif a == "--reverse":
        lo.reverse = True
    elif a == "--first-parent":
        lo.first_parent = True
    elif a == "--no-merges":
        lo.merges = False
    elif a == "--merges":
        lo.merges = True
    elif a in ("--decorate", "--decorate=short", "--decorate=full"):
        lo.decorate = True
    elif a in ("--no-decorate", "--decorate=no"):
        lo.decorate = False
    elif a == "--abbrev-commit":
        if lo.abbrev is None:
            lo.abbrev = 0
    elif a == "--no-abbrev-commit":
        lo.abbrev = None
    elif a.startswith("--abbrev="):
        lo.abbrev = int(a.split("=", 1)[1])
    elif a == "--all":
        lo.all = True
    elif parse_option(lo.diff, a):
        pass
    else:
        return None
    return i + 1


class Renderer:
    """Prints commits with the chosen layout; remembers separators between entries."""

    def __init__(self, repo, lo):
        self.repo = repo
        self.lo = lo
        self.shown = 0
        deco = build_decorations(repo) if (lo.decorate or (lo.user_format and "%d" in lo.user_format)
                                           or (lo.user_format and "%D" in lo.user_format)) else {}
        abbrev = lo.abbrev if lo.abbrev else None
        self.f = Formatter(repo, lo.date, deco if (lo.decorate or lo.user_format) else {}, abbrev,
                           abbrev_commit=lo.abbrev is not None)

    def header(self, sha, c):
        lo = self.lo
        f = self.f
        if lo.fmt == "oneline":
            if lo.oneline_full and lo.abbrev is None:
                return "%s%s %s\n" % (sha, f.decorate(sha), split_message(c.message)[0])
            return f.oneline(sha, c) + "\n"
        if lo.fmt == "user":
            return f.expand(lo.user_format, sha, c) + ("\n" if lo.terminator else "")
        if lo.fmt == "short":
            return f.short_fmt(sha, c)
        if lo.fmt in ("full", "fuller"):
            return f.full(sha, c, lo.fmt == "fuller")
        return f.medium(sha, c)

    def show(self, sha, pairs_fn, default_patch=True):
        lo = self.lo
        c = self.repo.read_commit(sha)
        if self.shown and lo.fmt not in ("oneline",) and not (lo.fmt == "user" and lo.terminator):
            out("\n")
        out(self.header(sha, c))
        self.shown += 1
        d = lo.diff
        if d.quiet or (d.patch is False and not d.any_format()):
            return
        want_patch = d.wants_patch(default_patch)
        if not (want_patch or d.any_format()):
            return
        if default_patch and len(c.parents) > 1:
            if d.any_format():
                # stat-like formats compare a merge with its first parent; the (combined) patch of a
                # clean merge is empty
                import copy
                d2 = copy.copy(d)
                d2.patch = False
                wrote = emit(self.repo, commit_pairs(self.repo, sha, d, None, first_parent=True), d2,
                             default_patch, "\n" if lo.fmt != "oneline" else "")
                if not wrote and lo.fmt != "oneline" and (d.stat or d.shortstat or want_patch):
                    out("\n")
            elif want_patch and lo.fmt != "oneline":
                out("\n")
            return
        pairs = pairs_fn(c)
        sep = "\n" if lo.fmt != "oneline" else ""
        emit(self.repo, pairs, d, default_patch, sep)


def commit_pairs(repo, sha, o, spec=None, first_parent=False):
    c = repo.read_commit(sha)
    if len(c.parents) > 1 and not first_parent:
        return []
    ok = (lambda p: True) if spec is None else spec.match
    left = {}
    if c.parents:
        left = {p: v for p, v in flatten_tree(repo, repo.read_commit(c.parents[0]).tree).items() if ok(p)}
    right = {p: v for p, v in flatten_tree(repo, c.tree).items() if ok(p)}
    pairs = D.maps_to_pairs(repo, D.tree_sides(repo, left), D.tree_sides(repo, right))
    if o.renames:
        pairs = D.detect_renames(pairs)
    return pairs


def _filtered_tree(repo, tree, spec):
    return {p: v for p, v in flatten_tree(repo, tree).items() if spec.match(p)}


def run(ctx, args):
    lo = LogOpts()
    words = []
    paths = []
    i = 0
    dashdash = False
    while i < len(args):
        a = args[i]
        if a == "--":
            dashdash = True
            paths = args[i + 1:]
            break
        if a.startswith("-") and len(a) > 1 and not a.startswith("^"):
            n = parse_common(lo, a, args, i)
            if n is None:
                raise Fatal("unrecognized argument: %s" % a, 128)
            i = n
            continue
        words.append(a)
        i += 1
    repo = ctx.repo()
    include, exclude = [], []
    for k, w in enumerate(words):
        try:
            if w.startswith("^") and len(w) > 1:
                exclude.append(repo.resolve_commit(w[1:]))
                continue
            if "..." in w:
                a_, _, b_ = w.partition("...")
                ra, rb = repo.resolve_commit(a_ or "HEAD"), repo.resolve_commit(b_ or "HEAD")
                include += [ra, rb]
                exclude += merge_bases(repo, ra, rb)
                continue
            if ".." in w:
                a_, _, b_ = w.partition("..")
                exclude.append(repo.resolve_commit(a_ or "HEAD"))
                include.append(repo.resolve_commit(b_ or "HEAD"))
                continue
            include.append(repo.resolve_commit(w))
        except (BadRevision, ObjectNotFound):
            if not dashdash and os.path.lexists(os.path.join(ctx.cwd, w)):
                paths = words[k:]
                break
            raise bad_arg(w)
    if lo.all:
        for _, sha in repo.refs.list("refs/"):
            try:
                include.append(repo.peel(sha, "commit"))
            except Exception:
                pass
        h = repo.head_sha()
        if h:
            include.append(h)
    if not include and not lo.all:
        h = repo.head_sha()
        if h is None:
            br = repo.refs.head_branch() or "HEAD"
            raise Fatal("your current branch '%s' does not have any commits yet" % br)
        include.append(h)
    spec = Pathspec(repo, paths) if paths else None

    parents_of = None
    treesame = {}
    if spec is not None:
        def same_as(sha, parent):
            key = (sha, parent)
            if key not in treesame:
                ct = repo.read_commit(sha).tree
                pt = repo.read_commit(parent).tree if parent else None
                a = _filtered_tree(repo, ct, spec)
                b = _filtered_tree(repo, pt, spec) if pt else {}
                treesame[key] = a == b
            return treesame[key]

        def parents_of(sha):
            ps = repo.read_commit(sha).parents
            if len(ps) > 1:
                for p in ps:
                    if same_as(sha, p):
                        return [p]
            return ps

    rend = Renderer(repo, lo)
    count = 0
    skipped = 0
    results = []
    for sha in walk(repo, include, exclude, lo.first_parent, parents_of):
        c = repo.read_commit(sha)
        if lo.merges is False and len(c.parents) > 1:
            continue
        if lo.merges is True and len(c.parents) <= 1:
            continue
        if spec is not None:
            if c.parents:
                if any(same_as(sha, p) for p in c.parents):
                    continue
            elif same_as(sha, None):
                continue
        if skipped < lo.skip:
            skipped += 1
            continue
        results.append(sha)
        count += 1
        if lo.max_count is not None and count >= lo.max_count:
            break
    if lo.reverse:
        results.reverse()
    for sha in results:
        rend.show(sha, lambda c, s=sha: commit_pairs(repo, s, lo.diff, spec), default_patch=False)
    if lo.fmt == "user" and not lo.terminator and rend.shown:
        pass
    return 0
