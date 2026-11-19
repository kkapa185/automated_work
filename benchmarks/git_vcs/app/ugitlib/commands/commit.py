"""git commit"""
import os
import stat
import sys

from .. import diff as D
from ..ident import get_ident, parse_date, format_tz
from ..index import Index, flatten_tree, write_tree
from ..objects import Commit, parse_ident
from ..pretty import format_date_style, split_message
from ..util import Fatal, err, expand_short, fsdecode, fsencode, out, usage_error, unknown_opt_msg
from ..worktree import entry_state, lstat, make_entry
from . import status as statuscmd
from .. import statuslib

USAGE = "git commit [-a | --interactive | --patch] [-s] [-v] [-u<mode>] [--amend]\n" \
        "           [--dry-run] [(-c | -C | --fixup | --squash) <commit>]\n" \
        "           [-F <file> | -m <msg>] [--reset-author] [--allow-empty]\n" \
        "           [--allow-empty-message] [--no-verify] [-e] [--author=<author>]\n" \
        "           [--date=<date>] [--cleanup=<mode>] [--[no-]status]\n" \
        "           [-i | -o] [--pathspec-from-file=<file> [--pathspec-file-nul]]\n" \
        "           [(--trailer <token>[(=|:)<value>])...] [-S[<keyid>]]\n" \
        "           [--] [<pathspec>...]"


def cleanup_message(msg):
    lines = [ln.rstrip() for ln in msg.split("\n")]
    res = []
    for ln in lines:
        if not ln and (not res or not res[-1]):
            continue
        res.append(ln)
    while res and not res[-1]:
        res.pop()
    return "\n".join(res) + "\n" if res else ""


def update_tracked(repo, index):
    """Stage modifications/deletions of tracked files (commit -a)."""
    changed = False
    for path in sorted({e.path for e in index.sorted_entries() if e.stage}):
        st = lstat(repo, path)
        if st is None or stat.S_ISDIR(st.st_mode):
            index.remove(path)
        else:
            index.add(make_entry(repo, path, st, None))
        changed = True
    for e in list(index.stage0()):
        state = entry_state(repo, index, e)
        if state == "clean":
            continue
        if state == "missing":
            index.remove(e.path)
        else:
            st = lstat(repo, e.path)
            index.add(make_entry(repo, e.path, st, e))
        changed = True
    return changed


def run(ctx, args):
    args = expand_short(args, "aqnsv", "mF")
    messages = []
    all_ = allow_empty = amend = quiet = allow_empty_msg = False
    author = date = None
    reset_author = False
    msgfile = None
    paths = []
    i = 0
    while i < len(args):
        a = args[i]

        def val():
            nonlocal i
            i += 1
            if i >= len(args):
                usage_error("switch `%s' requires a value" % a.lstrip("-")[:1], USAGE)
            return args[i]

        if a == "--":
            paths += args[i + 1:]
            break
        if a == "-m":
            messages.append(val())
        elif a.startswith("-m") and len(a) > 2 and not a.startswith("--"):
            messages.append(a[2:])
        elif a.startswith("--message="):
            messages.append(a.split("=", 1)[1])
        elif a == "--message":
            messages.append(val())
        elif a in ("-F", "--file"):
            msgfile = val()
        elif a.startswith("--file="):
            msgfile = a.split("=", 1)[1]
        elif a in ("-a", "--all"):
            all_ = True
        elif a == "--allow-empty":
            allow_empty = True
        elif a == "--allow-empty-message":
            allow_empty_msg = True
        elif a == "--amend":
            amend = True
        elif a in ("-q", "--quiet"):
            quiet = True
        elif a.startswith("--author="):
            author = a.split("=", 1)[1]
        elif a == "--author":
            author = val()
        elif a.startswith("--date="):
            date = a.split("=", 1)[1]
        elif a == "--date":
            date = val()
        elif a == "--reset-author":
            reset_author = True
        elif a in ("--no-edit", "-n", "--no-verify", "-s", "--signoff", "--no-status"):
            pass
        elif a.startswith("-") and a != "-":
            usage_error(unknown_opt_msg(a), USAGE)
        else:
            paths.append(a)
        i += 1
    repo = ctx.worktree_repo()
    file_message = None
    if msgfile is not None:
        try:
            file_message = sys.stdin.read() if msgfile == "-" else open(msgfile, "rb").read().decode(
                "utf-8", "surrogateescape")
        except OSError as e:
            raise Fatal("could not read log file '%s': %s" % (msgfile, e.strerror))
    if paths:
        raise Fatal("commit with pathspec is not supported; use 'git add' first")
    index = Index.load(repo)
    changed = False
    if all_:
        changed = update_tracked(repo, index)
    if index.has_conflicts():
        for path in sorted({e.path for e in index.sorted_entries() if e.stage}, key=fsencode):
            out("U\t%s\n" % path)
        err("error: Committing is not possible because you have unmerged files.\n"
            "hint: Fix them up in the work tree, and then use 'git add/rm <file>'\n"
            "hint: as appropriate to mark resolution and make a commit.\n")
        raise Fatal("Exiting because of an unresolved conflict.")
    head = repo.head_sha()
    merge_head_path = os.path.join(repo.gitdir, "MERGE_HEAD")
    merge_head = None
    if os.path.exists(merge_head_path):
        with open(merge_head_path) as f:
            merge_head = [ln.strip() for ln in f.read().split("\n") if ln.strip()]
    old = None
    if amend:
        if head is None:
            raise Fatal("You have nothing to amend.")
        old = repo.read_commit(head)
        if merge_head:
            raise Fatal("You are in the middle of a merge -- cannot amend.")
    tree = write_tree(repo, index)
    if amend:
        parents = list(old.parents)
        parent_tree = repo.read_commit(parents[0]).tree if parents else None
    else:
        parents = [head] if head else []
        if merge_head:
            parents += merge_head
        parent_tree = repo.read_commit(head).tree if head else None
    if not allow_empty and not merge_head and not (amend and len(old.parents) > 1) \
            and tree == (parent_tree or D_EMPTY()):
        st = statuslib.compute(repo, amend=amend)
        text, _ = statuscmd.render_long(repo, st, True, "normal", amend)
        if amend:
            out(text)
            err("You asked to amend the most recent commit, but doing so would make\n"
                "it empty. You can repeat your command with --allow-empty, or you can\n"
                "remove the commit entirely with \"git reset HEAD^\".\n")
        else:
            out(text)
        return 1
    # message
    if file_message is not None:
        message = cleanup_message(file_message)
    elif messages:
        message = cleanup_message("\n\n".join(messages))
    elif amend:
        message = old.message
    elif merge_head and os.path.exists(os.path.join(repo.gitdir, "MERGE_MSG")):
        with open(os.path.join(repo.gitdir, "MERGE_MSG"), "rb") as f:
            message = cleanup_message(fsdecode(f.read()))
    else:
        err("Aborting commit due to empty commit message.\n")
        return 1
    if not message.strip() and not allow_empty_msg:
        err("Aborting commit due to empty commit message.\n")
        return 1
    # identities
    cfg = repo.config
    env = dict(ctx.env)
    if date:
        try:
            ts, tz = parse_date(date)
        except ValueError:
            raise Fatal("invalid date format: %s" % date)
        env["GIT_AUTHOR_DATE"] = "%d %s" % (ts, format_tz(tz))
    if author:
        if "<" not in author or ">" not in author:
            raise Fatal("--author '%s' is not 'Name <email>' and matches no existing author" % author)
        nm, em = author.split("<", 1)
        env["GIT_AUTHOR_NAME"], env["GIT_AUTHOR_EMAIL"] = nm.strip(), em.split(">")[0]
    if amend and not reset_author and not author:
        a_ident = old.author
        if date:
            n_, e_, _, _ = parse_ident(a_ident)
            a_ident = get_ident("AUTHOR", cfg, dict(env, GIT_AUTHOR_NAME=n_, GIT_AUTHOR_EMAIL=e_))
    else:
        a_ident = get_ident("AUTHOR", cfg, env)
    c_ident = get_ident("COMMITTER", cfg, ctx.env)
    commit = Commit(tree, parents, a_ident, c_ident, message,
                    old.extra if amend and old.extra else [])
    sha = repo.odb.write("commit", commit.serialize())
    branch = repo.refs.head_branch()
    subj_line = message.split("\n", 1)[0]
    kind = "commit (initial)" if not parents else "commit (amend)" if amend else \
        "commit (merge)" if merge_head else "commit"
    if branch is not None:
        repo.update_ref("refs/heads/" + branch, sha, "%s: %s" % (kind, subj_line))
    else:
        repo.update_ref("HEAD", sha, "%s: %s" % (kind, subj_line))
    if changed:
        index.write(repo)
    for f in ("MERGE_HEAD", "MERGE_MSG", "MERGE_MODE", "SQUASH_MSG"):
        try:
            os.unlink(os.path.join(repo.gitdir, f))
        except OSError:
            pass
    if quiet:
        return 0
    subj, _ = split_message(message)
    label = branch if branch is not None else "detached HEAD"
    root = " (root-commit)" if not parents and not amend else ""
    lines = ["[%s%s %s] %s\n" % (label, root, repo.odb.shorten(sha), subj)]
    an, ae, _, _ = parse_ident(a_ident)
    cn, ce, _, _ = parse_ident(c_ident)
    if (an, ae) != (cn, ce):
        lines.append(" Author: %s <%s>\n" % (an, ae))
    if amend or date:
        _, _, ats, atz = parse_ident(a_ident)
        lines.append(" Date: %s\n" % format_date_style(ats, atz))
    out("".join(lines))
    left = D.tree_sides(repo, flatten_tree(repo, parents and repo.read_commit(parents[0]).tree or
                                           D_EMPTY(repo)) if parents else {})
    right = D.tree_sides(repo, flatten_tree(repo, tree))
    pairs = D.detect_renames(D.maps_to_pairs(repo, left, right))
    if pairs and len(parents) < 2:
        _, files, ins, dele = D.format_stat(pairs)
        out(D.stat_summary_line(files, ins, dele))
        out(D.summary_lines(pairs))
    return 0


def D_EMPTY(repo=None):
    from ..objects import EMPTY_TREE
    return EMPTY_TREE
