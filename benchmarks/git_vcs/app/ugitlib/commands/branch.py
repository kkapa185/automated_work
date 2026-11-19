"""git branch"""
import fnmatch

from ..objects import ObjectNotFound
from ..pretty import split_message
from ..refs import check_refname_format
from ..repo import BadRevision
from ..revwalk import is_ancestor
from ..util import Fatal, err, expand_short, fsencode, out, usage_error, unknown_opt_msg

USAGE = "git branch [<options>] [-r | -a] [--merged] [--no-merged]"


def _valid_branch(name):
    return check_refname_format("refs/heads/" + name) and not name.startswith("-") and name != "HEAD"


def run(ctx, args):
    args = expand_short(args, "dDmMfvralq")
    delete = force_delete = move = force_move = force = verbose = False
    show_current = remote = all_ = list_ = False
    pos = []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--":
            pos += args[i + 1:]
            break
        if a == "-d" or a == "--delete":
            delete = True
        elif a == "-D":
            delete = force_delete = True
        elif a == "-m" or a == "--move":
            move = True
        elif a == "-M":
            move = force_move = True
        elif a in ("-f", "--force"):
            force = True
        elif a in ("-v", "-vv", "--verbose"):
            verbose = True
        elif a == "--show-current":
            show_current = True
        elif a in ("-r", "--remotes"):
            remote = True
        elif a in ("-a", "--all"):
            all_ = True
        elif a in ("-l", "--list"):
            list_ = True
        elif a in ("-q", "--quiet", "--no-color", "--color=never"):
            pass
        elif a.startswith("-") and a != "-":
            usage_error(unknown_opt_msg(a), USAGE)
        else:
            pos.append(a)
        i += 1
    repo = ctx.repo()
    cur = repo.refs.head_branch()
    if show_current:
        if cur:
            out(cur + "\n")
        return 0
    if delete:
        return do_delete(ctx, repo, pos, force_delete or force, remote)
    if move:
        return do_move(repo, pos, force_move or force, cur)
    if list_ or not pos:
        return do_list(repo, pos, remote, all_, verbose, cur)
    name = pos[0]
    start = pos[1] if len(pos) > 1 else "HEAD"
    if len(pos) > 2:
        raise Fatal("too many arguments", 129)
    if not _valid_branch(name):
        raise Fatal("'%s' is not a valid branch name" % name)
    ref = "refs/heads/" + name
    if repo.refs.resolve(ref) and not force:
        raise Fatal("a branch named '%s' already exists" % name)
    if force and name == cur:
        raise Fatal("cannot force update the branch '%s' used by worktree at '%s'" % (name, repo.worktree))
    try:
        sha = repo.resolve_commit(start)
    except (BadRevision, ObjectNotFound):
        if start == "HEAD" and repo.head_sha() is None:
            raise Fatal("not a valid object name: '%s'" % (cur or "HEAD"))
        raise Fatal("not a valid object name: '%s'" % start)
    repo.update_ref(ref, sha, "branch: Created from %s" % start)
    return 0


def do_list(repo, patterns, remote, all_, verbose, cur):
    entries = []
    if not remote or all_:
        for n, s in repo.refs.list("refs/heads/"):
            entries.append((n[len("refs/heads/"):], s, "local"))
    if remote or all_:
        for n, s in repo.refs.list("refs/remotes/"):
            short = n[len("refs/remotes/"):]
            if short.endswith("/HEAD"):
                continue
            entries.append((("remotes/" + short) if all_ else short, s, "remote"))
    if patterns:
        entries = [e for e in entries if any(fnmatch.fnmatchcase(e[0], p) for p in patterns)]
    entries.sort(key=lambda e: (e[2] == "remote" if all_ else 0, fsencode(e[0])))
    lines = []
    head = repo.head_sha()
    detached = cur is None and head is not None
    if detached and not patterns and not remote:
        from .. import reflog
        info = reflog.detached_from(repo)
        lines.append(("* ", "(HEAD detached %s %s)" % (info if info else ("at", repo.odb.shorten(head))), head))
    width = max([len(e[0]) for e in entries] + [len(lines[0][1]) if lines else 0] or [0])
    for name, sha, kind in entries:
        mark = "* " if (kind == "local" and name == cur) else "  "
        lines.append((mark, name, sha))
    for mark, name, sha in lines:
        if verbose:
            subj = ""
            try:
                subj = split_message(repo.read_commit(sha).message)[0]
            except Exception:
                pass
            out("%s%-*s %s %s\n" % (mark, width, name, repo.odb.shorten(sha), subj))
        else:
            out("%s%s\n" % (mark, name))
    return 0


def do_delete(ctx, repo, names, force, remote):
    if not names:
        raise Fatal("branch name required")
    cur = repo.refs.head_branch()
    head = repo.head_sha()
    rc = 0
    for name in names:
        ref = ("refs/remotes/" if remote else "refs/heads/") + name
        sha = repo.refs.resolve(ref)
        if sha is None:
            err("error: %sbranch '%s' not found\n" % ("remote-tracking " if remote else "", name))
            rc = 1
            continue
        if not remote and name == cur:
            err("error: cannot delete branch '%s' used by worktree at '%s'\n" % (name, repo.worktree))
            rc = 1
            continue
        if not force and not remote:
            merged = head is not None and is_ancestor(repo, repo.peel(sha, "commit"), head)
            if not merged:
                err("error: the branch '%s' is not fully merged.\nIf you are sure you want to delete it, "
                    "run 'git branch -D %s'\n" % (name, name))
                rc = 1
                continue
        repo.refs.delete(ref)
        from .. import reflog
        reflog.remove(repo, ref)
        out("Deleted %sbranch %s (was %s).\n" % ("remote-tracking " if remote else "", name,
                                                  repo.odb.shorten(sha)))
    return rc


def do_move(repo, names, force, cur):
    if len(names) == 1:
        old, new = cur, names[0]
        if old is None:
            raise Fatal("cannot rename the current branch while not on any.")
    elif len(names) == 2:
        old, new = names
    else:
        raise Fatal("too many arguments", 129)
    sha = repo.refs.resolve("refs/heads/" + old)
    if not _valid_branch(new):
        raise Fatal("'%s' is not a valid branch name" % new)
    if sha is None:
        if old == cur:
            if repo.refs.resolve("refs/heads/" + new) and not force:
                raise Fatal("a branch named '%s' already exists" % new)
            repo.refs.set_symbolic("HEAD", "refs/heads/" + new)
            return 0
        raise Fatal("no branch named '%s'" % old)
    if repo.refs.resolve("refs/heads/" + new) and not force:
        raise Fatal("a branch named '%s' already exists" % new)
    if old == new:
        return 0
    if force and new == cur and old != cur:
        raise Fatal("cannot force update the branch '%s' used by worktree at '%s'" % (new, repo.worktree))
    from .. import reflog
    entries = reflog.read(repo, "refs/heads/" + old)
    repo.refs.update("refs/heads/" + new, sha)
    for o, n, ident, m in entries:
        reflog.append_raw(repo, "refs/heads/" + new, o, n, ident, m)
    reflog.append(repo, "refs/heads/" + new, sha, sha, "Branch: renamed refs/heads/%s to refs/heads/%s" % (old, new))
    if old == cur:
        repo.refs.set_symbolic("HEAD", "refs/heads/" + new)
        reflog.append(repo, "HEAD", sha, sha, "Branch: renamed refs/heads/%s to refs/heads/%s" % (old, new))
    repo.refs.delete("refs/heads/" + old)
    reflog.remove(repo, "refs/heads/" + old)
    return 0
