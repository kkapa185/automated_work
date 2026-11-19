"""git tag"""
import fnmatch
import sys

from ..ident import get_ident
from ..objects import ObjectNotFound, Tag
from ..refs import check_refname_format
from ..repo import BadRevision
from ..util import Fatal, err, expand_short, fsdecode, fsencode, out, usage_error, unknown_opt_msg
from .commit import cleanup_message

USAGE = "git tag [-a | -s | -u <key-id>] [-f] [-m <msg> | -F <file>] <tagname> [<commit> | <object>]"


def run(ctx, args):
    args = expand_short(args, "adfln", "mF")
    annotate = force = delete = list_ = False
    messages = []
    msgfile = None
    pos = []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--":
            pos += args[i + 1:]
            break
        if a in ("-a", "--annotate"):
            annotate = True
        elif a in ("-f", "--force"):
            force = True
        elif a in ("-d", "--delete"):
            delete = True
        elif a in ("-l", "--list"):
            list_ = True
        elif a == "-m":
            i += 1
            if i >= len(args):
                usage_error("switch `m' requires a value", USAGE)
            messages.append(args[i])
        elif a.startswith("-m") and len(a) > 2:
            messages.append(a[2:])
        elif a.startswith("--message="):
            messages.append(a.split("=", 1)[1])
        elif a in ("-F", "--file"):
            i += 1
            msgfile = args[i]
        elif a.startswith("-n") or a in ("--no-color", "--color=never"):
            pass
        elif a.startswith("-") and a != "-":
            usage_error(unknown_opt_msg(a), USAGE)
        else:
            pos.append(a)
        i += 1
    repo = ctx.repo()
    if delete:
        rc = 0
        for name in pos:
            ref = "refs/tags/" + name
            sha = repo.refs.resolve(ref)
            if sha is None:
                err("error: tag '%s' not found.\n" % name)
                rc = 1
                continue
            repo.refs.delete(ref)
            out("Deleted tag '%s' (was %s)\n" % (name, repo.odb.shorten(sha)))
        return rc
    if list_ or (not pos and not annotate and not messages and msgfile is None):
        pats = pos
        for n, _ in repo.refs.list("refs/tags/"):
            short = n[len("refs/tags/"):]
            if not pats or any(fnmatch.fnmatchcase(short, p) for p in pats):
                out(short + "\n")
        return 0
    if not pos:
        raise Fatal(USAGE, 129, prefix="usage: ")
    name = pos[0]
    target = pos[1] if len(pos) > 1 else "HEAD"
    if len(pos) > 2:
        raise Fatal(USAGE, 129, prefix="usage: ")
    if not check_refname_format("refs/tags/" + name) or name.startswith("-"):
        raise Fatal("'%s' is not a valid tag name." % name)
    ref = "refs/tags/" + name
    old = repo.refs.resolve(ref)
    if old and not force:
        raise Fatal("tag '%s' already exists" % name)
    try:
        sha = repo.resolve(target)
        typ = repo.odb.read(sha)[0]
    except (BadRevision, ObjectNotFound):
        if target == "HEAD":
            raise Fatal("Failed to resolve 'HEAD' as a valid ref.")
        raise Fatal("Failed to resolve '%s' as a valid ref." % target)
    if messages or msgfile is not None:
        annotate = True
    if annotate:
        if msgfile is not None:
            raw = sys.stdin.read() if msgfile == "-" else open(msgfile, "rb").read().decode(
                "utf-8", "surrogateescape")
            message = cleanup_message(raw)
        elif messages:
            message = cleanup_message("\n\n".join(messages))
        else:
            raise Fatal("no tag message?")
        if not message.strip():
            raise Fatal("no tag message?")
        tagger = get_ident("COMMITTER", repo.config, ctx.env)
        tag = Tag(sha, typ, name, tagger, message)
        sha = repo.odb.write("tag", tag.serialize())
    repo.refs.update(ref, sha)
    if old and force:
        out("Updated tag '%s' (was %s)\n" % (name, repo.odb.shorten(old)))
    return 0
