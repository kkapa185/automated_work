"""git checkout (and the shared branch-switching logic used by git switch)"""
import os

from .. import checkout as C
from ..diffout import DiffOpts
from ..index import Index, flatten_tree
from ..objects import ObjectNotFound
from ..pathspec import Pathspec
from ..pretty import split_message
from ..refs import check_refname_format
from ..repo import BadRevision
from ..util import Fatal, err, expand_short, out, usage_error, unknown_opt_msg

USAGE = "git checkout [<options>] <branch>"

DETACH_ADVICE = """Note: switching to '%s'.

You are in 'detached HEAD' state. You can look around, make experimental
changes and commit them, and you can discard any commits you make in this
state without impacting any branches by switching back to a branch.

If you want to create a new branch to retain commits you create, you may
do so (now or later) by using -c with the switch command. Example:

  git switch -c <new-branch-name>

Or undo this operation with:

  git switch -

Turn off this advice by setting config variable advice.detachedHead to false

"""


def show_local_changes(repo):
    """The 'M\\tpath' lines git prints after a switch when local changes were carried over."""
    from .diff import build_pairs
    o = DiffOpts()
    o.renames = False
    pairs, _ = build_pairs(repo, o, "worktree", ["HEAD"], None)
    for p in pairs:
        letter = p.status if p.status in ("A", "D", "T") else "M"
        out("%s\t%s\n" % (letter, p.path))


def subject_of(repo, sha):
    try:
        return split_message(repo.read_commit(sha).message)[0]
    except Exception:
        return ""


def switch_to(repo, target_sha, new_head, force, quiet, label_for_detach, create_branch=None,
              branch_start_label=None, create_exists=False, moving_to=None, explicit_detach=False):
    """Move HEAD/index/worktree to commit ``target_sha``.

    new_head: ('branch', name) or ('detach', None)."""
    index = Index.load(repo)
    old_sha = repo.head_sha()
    old_branch = repo.refs.head_branch()
    old_map = C.commit_map(repo, old_sha)
    new_map = C.commit_map(repo, target_sha)
    try:
        plan = C.plan_switch(repo, index, old_map, new_map, force, "checkout")
    except C.Abort as a:
        err(a.text + "\n")
        return 1
    C.apply_plan(repo, index, plan)
    C.refresh_index(repo, index)
    index.write(repo)
    if create_branch is not None:
        repo.update_ref("refs/heads/" + create_branch, target_sha,
                        "branch: Created from %s" % (branch_start_label or "HEAD") if not create_exists
                        else "branch: Reset to %s" % (branch_start_label or "HEAD"))
    kind, name = new_head
    was_detached = old_branch is None and old_sha is not None
    moving_from = old_branch if old_branch is not None else (old_sha or "HEAD")
    if kind == "branch":
        repo.refs.set_symbolic("HEAD", "refs/heads/" + name)
    else:
        C.set_head_detached(repo, target_sha)
    if not (kind == "detach" and was_detached and old_sha == target_sha):
        repo.log_head_move(old_sha, target_sha, "checkout: moving from %s to %s" % (
            moving_from, name if kind == "branch" else (moving_to or target_sha)))
    if kind == "detach":
        if was_detached and old_sha != target_sha and not quiet:
            err(leaving_notice(repo, old_sha, target_sha))
        if not quiet:
            if not was_detached and not explicit_detach:
                err(DETACH_ADVICE % label_for_detach)
            err("HEAD is now at %s %s\n" % (repo.odb.shorten(target_sha), subject_of(repo, target_sha)))
    else:
        if was_detached and not quiet and old_sha != target_sha:
            err(leaving_notice(repo, old_sha, target_sha))
    return 0


def leaving_notice(repo, old_sha, new_sha):
    """Text printed when leaving a detached HEAD: either the lost-commits warning or the
    'Previous HEAD position' line."""
    from ..revwalk import walk
    tips = []
    for _, sha in repo.refs.list("refs/"):
        try:
            tips.append(repo.peel(sha, "commit"))
        except Exception:
            pass
    lost = list(walk(repo, [old_sha], tips + [new_sha]))
    if not lost:
        return "Previous HEAD position was %s %s\n" % (repo.odb.shorten(old_sha), subject_of(repo, old_sha))
    lines = ["Warning: you are leaving %d commit%s behind, not connected to\nany of your branches:\n\n" % (
        len(lost), "" if len(lost) == 1 else "s")]
    for c in lost:
        lines.append("  %s %s\n" % (repo.odb.shorten(c), subject_of(repo, c)))
    lines.append("\nIf you want to keep %s by creating a new branch, this may be a good time\n"
                 "to do so with:\n\n git branch <new-branch-name> %s\n\n" % (
                     "it" if len(lost) == 1 else "them", repo.odb.shorten(old_sha)))
    return "".join(lines)


def local_changes_after(repo):
    if repo.head_sha():
        show_local_changes(repo)


def do_branch_switch(ctx, repo, name, force, quiet):
    cur = repo.refs.head_branch()
    sha = repo.refs.resolve("refs/heads/" + name)
    if sha is None:
        raise Fatal("invalid reference: %s" % name)
    if cur == name:
        if force:
            rc = switch_to(repo, sha, ("branch", name), True, True, None)
            if rc:
                return rc
        else:
            repo.log_head_move(sha, sha, "checkout: moving from %s to %s" % (name, name))
        local_changes_after(repo) if not force else None
        if not quiet:
            err("Already on '%s'\n" % name)
        return 0
    rc = switch_to(repo, sha, ("branch", name), force, quiet, None)
    if rc:
        return rc
    local_changes_after(repo) if not force else None
    if not quiet:
        err("Switched to branch '%s'\n" % name)
    return 0


def do_create(ctx, repo, name, start, force_create, force, quiet, label="HEAD", switch_style=False):
    if not check_refname_format("refs/heads/" + name) or name.startswith("-"):
        raise Fatal("'%s' is not a valid branch name" % name)
    exists = repo.refs.resolve("refs/heads/" + name) is not None
    if exists and not force_create:
        raise Fatal("a branch named '%s' already exists" % name)
    head = repo.head_sha()
    if start is None:
        sha = head
    else:
        try:
            sha = repo.resolve_commit(start)
        except (BadRevision, ObjectNotFound):
            if switch_style:
                raise Fatal("invalid reference: %s" % start)
            raise Fatal("'%s' is not a commit and a branch '%s' cannot be created from it" % (start, name))
    if sha is None:
        # unborn branch: just point HEAD at the new name
        repo.log_head_move(None, None, "checkout: moving from %s to %s" % (
            repo.refs.head_branch() or "HEAD", name)) if False else None
        repo.refs.set_symbolic("HEAD", "refs/heads/" + name)
        if not quiet:
            err("Switched to a new branch '%s'\n" % name)
        return 0
    rc = switch_to(repo, sha, ("branch", name), force, quiet, None, create_branch=name,
                   branch_start_label=start, create_exists=exists)
    if rc:
        return rc
    if sha != head:
        local_changes_after(repo) if not force else None
    if not quiet:
        err("%s '%s'\n" % ("Switched to and reset branch" if exists else "Switched to a new branch", name))
    return 0


def do_detach(ctx, repo, spec, force, quiet, explicit=False):
    try:
        sha = repo.resolve_commit(spec)
    except (BadRevision, ObjectNotFound):
        raise Fatal("invalid reference: %s" % spec)
    old = repo.head_sha()
    rc = switch_to(repo, sha, ("detach", None), force, quiet, spec, moving_to=spec, explicit_detach=explicit)
    if rc:
        return rc
    local_changes_after(repo) if not force else None
    return 0


def run(ctx, args):
    args = expand_short(args, "bBfqm", "")
    create = force_create = None
    force = quiet = detach = False
    ours = theirs = False
    orphan = None
    pos = []
    dashdash = None
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--":
            dashdash = args[i + 1:]
            break
        if a in ("-b", "-B"):
            i += 1
            if i >= len(args):
                usage_error("switch `%s' requires a value" % a[1], USAGE)
            create = args[i]
            force_create = a == "-B"
        elif a in ("-f", "--force"):
            force = True
        elif a in ("-q", "--quiet"):
            quiet = True
        elif a == "--detach":
            detach = True
        elif a == "--ours":
            ours = True
        elif a == "--theirs":
            theirs = True
        elif a == "--orphan":
            i += 1
            orphan = args[i]
        elif a in ("-m", "--merge", "--no-guess", "--no-track", "-t", "--track", "--progress", "--no-progress"):
            pass
        elif a.startswith("-") and a != "-":
            usage_error(unknown_opt_msg(a), USAGE)
        else:
            pos.append(a)
        i += 1
    repo = ctx.worktree_repo()
    if orphan is not None:
        raise Fatal("--orphan is not supported")
    # path mode: explicit '--' or arguments that are not a branch/commit
    if dashdash is not None:
        tree = pos[0] if pos else None
        if len(pos) > 1:
            raise Fatal("only one reference expected")
        return checkout_paths(ctx, repo, tree, dashdash, ours, theirs, quiet, report=False)
    if create is not None:
        if len(pos) > 1:
            raise Fatal("Cannot update paths and switch to branch '%s' at the same time." % create)
        return do_create(ctx, repo, create, pos[0] if pos else None, force_create, force, quiet)
    if not pos:
        if detach:
            return do_detach(ctx, repo, "HEAD", force, quiet, True)
        raise Fatal(USAGE, 129, prefix="usage: ")
    first = pos[0]
    if first == "-":
        from .. import reflog
        prev = reflog.previous_checkout(repo)
        if prev is None:
            raise Fatal("invalid reference: @{-1}")
        first = prev
    if not detach and repo.refs.resolve("refs/heads/" + first) is not None and len(pos) == 1:
        return do_branch_switch(ctx, repo, first, force, quiet)
    try:
        sha = repo.resolve(first)
        is_commitish = repo.odb.exists(sha)
        if is_commitish:
            repo.peel(sha, "commit")
    except (BadRevision, ObjectNotFound):
        is_commitish = False
    if is_commitish and (len(pos) == 1 or detach):
        # `git checkout <paths>` is only chosen when it is not a revision
        return do_detach(ctx, repo, first, force, quiet, detach)
    if is_commitish and len(pos) > 1:
        return checkout_paths(ctx, repo, first, pos[1:], ours, theirs, quiet, report=not quiet)
    return checkout_paths(ctx, repo, None, pos, ours, theirs, quiet, report=not quiet)


def checkout_paths(ctx, repo, tree, paths, ours, theirs, quiet, report=False):
    from ..restore_lib import restore_paths
    return restore_paths(ctx, repo, paths, source=tree, staged=bool(tree), worktree=True,
                         ours=ours, theirs=theirs, checkout_style=True, report=report)
