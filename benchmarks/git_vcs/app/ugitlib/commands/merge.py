"""git merge"""
import os

from .. import checkout as C
from .. import diff as D
from ..ident import get_ident
from ..index import Index, IndexEntry, flatten_tree, write_tree
from ..merge3 import merge_trees
from ..objects import Commit, ObjectNotFound
from ..pretty import split_message
from ..repo import BadRevision
from ..revwalk import is_ancestor, merge_bases
from ..util import Exit, Fatal, err, expand_short, fsencode, out, usage_error, unknown_opt_msg
from ..worktree import entry_state

USAGE = "git merge [<options>] [<commit>...]"


def default_message(repo, arg, sha, cur):
    full = repo.dwim_ref(arg)
    extra = ""
    if full is not None and full.startswith("refs/heads/"):
        kind = "branch"
    elif full is not None and full.startswith("refs/tags/"):
        kind = "tag"
        raw = repo.refs.resolve(full)
        if raw and repo.odb.read(raw)[0] == "tag":
            from ..objects import parse_tag
            extra = "\n" + parse_tag(repo.odb.read(raw)[1]).message.rstrip("\n") + "\n"
    elif full is not None and full.startswith("refs/remotes/"):
        kind = "remote-tracking branch"
    else:
        kind = "commit"
    msg = "Merge %s '%s'" % (kind, arg)
    name = cur or "HEAD"
    if name not in ("master", "main"):
        msg += " into %s" % name
    return msg + "\n" + extra


def write_state(repo, target, message, no_ff, conflicts=()):
    g = repo.gitdir
    with open(os.path.join(g, "MERGE_HEAD"), "w") as f:
        f.write(target + "\n")
    body = message
    if conflicts:
        body += "\n# Conflicts:\n" + "".join("#\t%s\n" % p for p in conflicts)
    with open(os.path.join(g, "MERGE_MSG"), "wb") as f:
        f.write(body.encode("utf-8", "surrogateescape"))
    with open(os.path.join(g, "MERGE_MODE"), "w") as f:
        f.write("no-ff" if no_ff else "")


def stat_between(repo, old_commit, new_commit):
    left = D.tree_sides(repo, C.commit_map(repo, old_commit))
    right = D.tree_sides(repo, C.commit_map(repo, new_commit))
    pairs = D.detect_renames(D.maps_to_pairs(repo, left, right))
    return D.format_stat_full(pairs) + D.summary_lines(pairs) if pairs else ""


def virtual_base(repo, bases, depth=0):
    """Merge several merge bases into one virtual tree map (recursive strategy)."""
    cur = C.commit_map(repo, bases[0])
    cur_commit = bases[0]
    for b in bases[1:]:
        common = merge_bases(repo, cur_commit, b)
        if len(common) > 1 and depth < 8:
            cbase = virtual_base(repo, common, depth + 1)
        elif common:
            cbase = C.commit_map(repo, common[0])
        else:
            cbase = {}
        res = merge_trees(repo, cbase, cur, C.commit_map(repo, b), b"Temporary merge branch 1",
                          b"Temporary merge branch 2")
        merged = dict(res.clean)
        for p, (mode, data) in res.worktree.items():
            merged[p] = (mode, repo.odb.write("blob", data))
        cur = merged
        cur_commit = bases[0]
    return cur


def do_abort(repo):
    mh = os.path.join(repo.gitdir, "MERGE_HEAD")
    if not os.path.exists(mh):
        raise Fatal("There is no merge to abort (MERGE_HEAD missing).")
    index = Index.load(repo)
    head = C.commit_map(repo, repo.head_sha())
    plan = []
    unmerged = {e.path for e in index.sorted_entries() if e.stage}
    for p in set(head) | {e.path for e in index.sorted_entries()}:
        e = index.get(p, 0)
        t = head.get(p)
        if p in unmerged:
            index.remove(p)
            plan.append((p, t))
        elif ((e.mode, e.sha) if e else None) != t:
            plan.append((p, t))
    plan.sort(key=lambda x: (x[1] is not None, fsencode(x[0])))
    C.apply_plan(repo, index, plan)
    index.write(repo)
    for f in ("MERGE_HEAD", "MERGE_MSG", "MERGE_MODE", "AUTO_MERGE", "SQUASH_MSG"):
        try:
            os.unlink(os.path.join(repo.gitdir, f))
        except OSError:
            pass
    return 0


def run(ctx, args):
    args = expand_short(args, "qe", "m")
    message = None
    ff = "yes"
    no_commit = abort = quiet = False
    pos = []
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("-m", "--message"):
            i += 1
            if i >= len(args):
                usage_error("switch `m' requires a value", USAGE)
            message = args[i]
        elif a.startswith("--message="):
            message = a.split("=", 1)[1]
        elif a == "--no-ff":
            ff = "no"
        elif a == "--ff":
            ff = "yes"
        elif a == "--ff-only":
            ff = "only"
        elif a == "--no-commit":
            no_commit = True
        elif a == "--commit":
            no_commit = False
        elif a == "--abort":
            abort = True
        elif a in ("-q", "--quiet"):
            quiet = True
        elif a in ("--no-edit", "-e", "--edit", "--no-stat", "--stat", "--no-verify", "--no-log", "--log"):
            pass
        elif a.startswith("-") and a != "-":
            usage_error(unknown_opt_msg(a), USAGE)
        else:
            pos.append(a)
        i += 1
    repo = ctx.worktree_repo()
    if abort:
        return do_abort(repo)
    index = Index.load(repo)
    if index.has_conflicts():
        err("error: Merging is not possible because you have unmerged files.\n"
            "hint: Fix them up in the work tree, and then use 'git add/rm <file>'\n"
            "hint: as appropriate to mark resolution and make a commit.\n")
        raise Fatal("Exiting because of an unresolved conflict.")
    if os.path.exists(os.path.join(repo.gitdir, "MERGE_HEAD")):
        raise Fatal("You have not concluded your merge (MERGE_HEAD exists).\n"
                    "Please, commit your changes before you merge.")
    if not pos:
        raise Fatal("No remote for the current branch.")
    if len(pos) > 1:
        raise Fatal("octopus merges are not supported")
    arg = pos[0]
    try:
        target = repo.resolve_commit(arg)
    except (BadRevision, ObjectNotFound):
        err("merge: %s - not something we can merge\n" % arg)
        return 1
    head = repo.head_sha()
    cur = repo.refs.head_branch()
    if head is not None:
        _set_orig_head(repo, head)
    if head is None:
        # merging into an unborn branch: behave like a checkout of the target
        old_map, new_map = {}, C.commit_map(repo, target)
        plan = C.plan_switch(repo, index, old_map, new_map, False, "merge")
        C.apply_plan(repo, index, plan)
        index.write(repo)
        if cur:
            repo.update_ref("refs/heads/" + cur, target, "merge %s: initial pull" % arg)
        else:
            C.set_head_detached(repo, target)
        return 0
    if is_ancestor(repo, target, head):
        out("Already up to date.\n")
        return 0
    can_ff = is_ancestor(repo, head, target)
    if can_ff and ff != "no":
        out("Updating %s..%s\n" % (repo.odb.shorten(head), repo.odb.shorten(target)))
        try:
            plan = C.plan_switch(repo, index, C.commit_map(repo, head), C.commit_map(repo, target),
                                 False, "merge")
        except C.Abort as a:
            err(a.text + "\n")
            return 1
        C.apply_plan(repo, index, plan)
        C.refresh_index(repo, index)
        index.write(repo)
        _set_orig_head(repo, head)
        if cur:
            repo.update_ref("refs/heads/" + cur, target, "merge %s: Fast-forward" % arg)
        else:
            repo.update_ref("HEAD", target, "merge %s: Fast-forward" % arg)
        out("Fast-forward\n")
        out(stat_between(repo, head, target))
        return 0
    bases = merge_bases(repo, head, target)
    if not bases:
        raise Fatal("refusing to merge unrelated histories")
    if ff == "only":
        err("hint: Diverging branches can't be fast-forwarded, you need to either:\n"
            "hint: \n"
            "hint: \tgit merge --no-ff\n"
            "hint: \n"
            "hint: or:\n"
            "hint: \n"
            "hint: \tgit rebase\n"
            "hint: \n"
            "hint: Disable this message with \"git config advice.diverging false\"\n")
        raise Fatal("Not possible to fast-forward, aborting.")
    base_map = C.commit_map(repo, bases[0]) if len(bases) == 1 else virtual_base(repo, bases)
    ours = C.commit_map(repo, head)
    theirs = C.commit_map(repo, target)
    res = merge_trees(repo, base_map, ours, theirs, b"HEAD", arg.encode("utf-8", "surrogateescape"))

    # which paths does the merge change in the worktree?
    final = {}
    for p, v in res.clean.items():
        final[p] = v
    every = set(final) | set(res.conflicts)
    for p in every:
        parts = p.split("/")
        for k in range(1, len(parts)):
            if "/".join(parts[:k]) in every:
                err("error: merging file/directory conflicts (%s) is not supported\n" % "/".join(parts[:k]))
                return 2
    touched = []
    for p in set(ours) | set(final) | set(res.conflicts):
        if p in res.conflicts:
            touched.append(p)
        elif final.get(p) != ours.get(p):
            touched.append(p)
    overwritten, untracked, dirty = [], [], []
    head_index = {p: v for p, v in ours.items()}
    # a true merge requires the index to match HEAD (any staged difference is refused)
    cur_index = {e.path: (e.mode, e.sha) for e in index.stage0()}
    for p in set(cur_index) | set(head_index):
        if cur_index.get(p) != head_index.get(p):
            overwritten.append(p)
    for p in sorted(touched, key=fsencode):
        e = index.get(p, 0)
        if e is not None:
            if (e.mode, e.sha) == head_index.get(p) and entry_state(repo, index, e) == "modified":
                dirty.append(p)
        elif p not in ours:
            if C._untracked_in_way(repo, index, p):
                untracked.append(p)
    if overwritten:
        err("error: Your local changes to the following files would be overwritten by merge:\n%s\n"
            "Merge with strategy ort failed.\n" % "\n".join("  " + p for p in sorted(overwritten, key=fsencode)))
        return 2
    if untracked or dirty:
        err(C.refusal("merge", [], untracked, dirty) + "\n")
        err("Merge with strategy ort failed.\n")
        return 2

    # apply to worktree and index
    for p in sorted(touched, key=fsencode):
        if p in res.conflicts:
            continue
        t = final.get(p)
        if t is None:
            C.remove_file(repo, p)
            index.remove(p)
        else:
            st = C.write_file(repo, p, t[0], t[1])
            index.add(IndexEntry(p, t[1], t[0], 0, st))
    conflict_paths = sorted(res.conflicts, key=fsencode)
    for p in conflict_paths:
        mode, data = res.worktree[p]
        C.remove_file(repo, p) if os.path.isdir(os.path.join(repo.worktree, p)) else None
        full = os.path.join(repo.worktree, p)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        if os.path.lexists(full):
            os.unlink(full)
        fd = os.open(full, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o777 if mode == 0o100755 else 0o666)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        index.remove(p)
        for stage, (m, s) in res.conflicts[p].items():
            index.add(IndexEntry(p, s, m, stage), replace=False)
    index.write(repo)
    _set_orig_head(repo, head)
    for m in res.messages:
        out(m + "\n")
    for m in res.errors:
        err(m + "\n")
    msg = message + "\n" if message is not None else default_message(repo, arg, target, cur)
    if message is not None:
        msg = message.rstrip("\n") + "\n"
    if res.conflicts:
        write_state(repo, target, msg, ff == "no", conflict_paths)
        out("Automatic merge failed; fix conflicts and then commit the result.\n")
        return 1
    if no_commit:
        write_state(repo, target, msg, ff == "no")
        err("Automatic merge went well; stopped before committing as requested\n")
        return 0
    tree = write_tree(repo, index)
    commit = Commit(tree, [head, target], get_ident("AUTHOR", repo.config, ctx.env),
                    get_ident("COMMITTER", repo.config, ctx.env), msg)
    sha = repo.odb.write("commit", commit.serialize())
    if cur:
        repo.update_ref("refs/heads/" + cur, sha, "merge %s: Merge made by the 'ort' strategy." % arg)
    else:
        repo.update_ref("HEAD", sha, "merge %s: Merge made by the 'ort' strategy." % arg)
    if not quiet:
        out("Merge made by the 'ort' strategy.\n")
        out(stat_between(repo, head, sha))
    return 0


def _set_orig_head(repo, head):
    with open(os.path.join(repo.gitdir, "ORIG_HEAD"), "w") as f:
        f.write(head + "\n")
