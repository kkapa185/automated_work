"""git show"""
from ..objects import ObjectNotFound, mode_type, parse_tag, parse_tree
from ..pathspec import Pathspec
from ..pretty import format_date_style
from ..objects import parse_ident
from ..repo import BadRevision
from ..util import Fatal, out, quote_path
from .diff import bad_arg
from .log import LogOpts, Renderer, commit_pairs, parse_common


def run(ctx, args):
    lo = LogOpts()
    words = []
    paths = []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--":
            paths = args[i + 1:]
            break
        if a.startswith("-") and len(a) > 1:
            n = parse_common(lo, a, args, i)
            if n is None:
                raise Fatal("unrecognized argument: %s" % a, 128)
            i = n
            continue
        words.append(a)
        i += 1
    repo = ctx.repo()
    if not words:
        words = ["HEAD"]
    spec = Pathspec(repo, paths) if paths else None
    rend = Renderer(repo, lo)
    for w in words:
        try:
            sha = repo.resolve(w)
            typ, data = repo.odb.read(sha)
        except (BadRevision, ObjectNotFound):
            if ":" in w and not w.startswith(":"):
                rev, _, path = w.partition(":")
                try:
                    repo.resolve(rev)
                except (BadRevision, ObjectNotFound):
                    raise bad_arg(w)
                raise Fatal("path '%s' does not exist in '%s'" % (path, rev))
            raise bad_arg(w)
        show_object(repo, rend, lo, w, sha, typ, data, spec)
    return 0


def show_object(repo, rend, lo, name, sha, typ, data, spec):
    if typ == "commit":
        if spec is not None and not commit_pairs(repo, sha, lo.diff, spec):
            return
        rend.show(sha, lambda c: commit_pairs(repo, sha, lo.diff, spec), default_patch=True)
    elif typ == "tag":
        t = parse_tag(data)
        if rend.shown:
            out("\n")
        out("tag %s\n" % t.name)
        if t.tagger:
            n, e, ts, tz = parse_ident(t.tagger)
            out("Tagger: %s <%s>\n" % (n, e))
            out("Date:   %s\n" % format_date_style(ts, tz, lo.date))
        out("\n" + t.message)
        if not t.message.endswith("\n"):
            out("\n")
        rend.shown += 1
        t2, d2 = repo.odb.read(t.object)
        out("\n")
        rend.shown = 0
        show_object(repo, rend, lo, t.object, t.object, t2, d2, spec)
    elif typ == "tree":
        if rend.shown:
            out("\n")
        out("tree %s\n\n" % name)
        for mode, ename, esha in parse_tree(data):
            out(quote_path(ename) + ("/" if mode == 0o40000 else "") + "\n")
        rend.shown += 1
    else:
        out(data)
        rend.shown += 1
