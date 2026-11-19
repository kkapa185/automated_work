"""git status"""
import posixpath

from .. import statuslib
from ..objects import ObjectNotFound
from ..pathspec import Pathspec
from ..util import expand_short, fsencode, out, quote_path, usage_error, unknown_opt_msg
import os

USAGE = "git status [<options>] [--] [<pathspec>...]"

UNMERGED_LABELS = {
    frozenset([1, 2, 3]): "both modified:",
    frozenset([2, 3]): "both added:",
    frozenset([1, 2]): "deleted by them:",
    frozenset([1, 3]): "deleted by us:",
    frozenset([2]): "added by us:",
    frozenset([3]): "added by them:",
    frozenset([1]): "both deleted:",
}
UNMERGED_SHORT = {
    frozenset([1, 2, 3]): "UU", frozenset([2, 3]): "AA", frozenset([1, 2]): "UD",
    frozenset([1, 3]): "DU", frozenset([2]): "AU", frozenset([3]): "UA", frozenset([1]): "DD",
}
STAGED_LABELS = {"A": "new file:", "M": "modified:", "D": "deleted:", "R": "renamed:", "T": "typechange:"}


def rel(repo, path, full=False):
    if full or not repo.prefix:
        return path
    return posixpath.relpath(path.rstrip("/"), repo.prefix.rstrip("/")) + ("/" if path.endswith("/") else "")


def head_line(repo, st):
    if st.branch is not None:
        return "On branch %s" % st.branch
    if st.head:
        from .. import reflog
        info = reflog.detached_from(repo)
        if info is None:
            return "HEAD detached at %s" % repo.odb.shorten(st.head)
        return "HEAD detached %s %s" % info
    return "HEAD detached"


def render_long(repo, st, commit_template=False, untracked_mode="normal", amend=False):
    """Return (text, has_staged_changes)."""
    L = []
    L.append(head_line(repo, st) + "\n")
    unborn = st.head is None
    if unborn:
        L.append("\n%s\n\n" % ("Initial commit" if commit_template else "No commits yet"))
    merging = os.path.exists(os.path.join(repo.gitdir, "MERGE_HEAD"))
    if st.unmerged:
        L.append("You have unmerged paths.\n  (fix conflicts and run \"git commit\")\n"
                 "  (use \"git merge --abort\" to abort the merge)\n\n")
    elif merging:
        L.append("All conflicts fixed but you are still merging.\n  (use \"git commit\" to conclude merge)\n\n")
    q = lambda p: quote_path(rel(repo, p))
    if st.staged:
        L.append("Changes to be committed:\n")
        if merging or st.unmerged:
            pass
        elif unborn:
            L.append("  (use \"git rm --cached <file>...\" to unstage)\n")
        else:
            L.append("  (use \"git restore --staged <file>...\" to unstage)\n")
        for p in st.staged:
            label = STAGED_LABELS[p.status]
            if p.status == "R":
                name = "%s -> %s" % (q(p.old_path), q(p.new_path))
            else:
                name = q(p.path)
            L.append("\t%-12s%s\n" % (label, name))
        L.append("\n")
    if st.unmerged:
        deletions = any(not ({2, 3} <= set(s)) for s in st.unmerged.values())
        L.append("Unmerged paths:\n  (use \"git add%s <file>...\" %s)\n" % (
            "/rm" if deletions else "", "as appropriate to mark resolution" if deletions else "to mark resolution"))
        for path in sorted(st.unmerged, key=fsencode):
            label = UNMERGED_LABELS.get(frozenset(st.unmerged[path]), "both modified:")
            L.append("\t%-17s%s\n" % (label, q(path)))
        L.append("\n")
    if st.unstaged:
        has_del = any(c == "D" for c, _ in st.unstaged)
        L.append("Changes not staged for commit:\n")
        L.append("  (use \"git add%s <file>...\" to update what will be committed)\n" % ("/rm" if has_del else ""))
        L.append("  (use \"git restore <file>...\" to discard changes in working directory)\n")
        labels = {"M": "modified:", "D": "deleted:", "T": "typechange:"}
        for code, path in st.unstaged:
            L.append("\t%-12s%s\n" % (labels[code], q(path)))
        L.append("\n")
    if st.untracked:
        L.append("Untracked files:\n  (use \"git add <file>...\" to include in what will be committed)\n")
        for p in st.untracked:
            L.append("\t%s\n" % q(p))
        L.append("\n")
    if st.ignored:
        L.append("Ignored files:\n  (use \"git add -f <file>...\" to include in what will be committed)\n")
        for p in st.ignored:
            L.append("\t%s\n" % q(p))
        L.append("\n")
    committable = bool(st.staged)
    if untracked_mode == "no" and committable:
        L.append("Untracked files not listed (use -u option to show untracked files)\n")
    if not committable:
        if amend:
            L.append("No changes\n")
        elif st.unstaged or st.unmerged:
            L.append("no changes added to commit (use \"git add\" and/or \"git commit -a\")\n")
        elif st.untracked:
            L.append("nothing added to commit but untracked files present (use \"git add\" to track)\n")
        elif unborn:
            L.append("nothing to commit (create/copy files and use \"git add\" to track)\n")
        elif untracked_mode == "no":
            L.append("nothing to commit (use -u to show untracked files)\n")
        else:
            L.append("nothing to commit, working tree clean\n")
    return "".join(L), committable


def short_lines(repo, st, porcelain, z=False, branch=False):
    """Lines of the short format."""
    rows = {}
    for p in st.staged:
        key = p.new_path
        rows[key] = [p.status, " ", p.old_path if p.status == "R" else None]
    for path, stages in st.unmerged.items():
        rows[path] = [UNMERGED_SHORT.get(frozenset(stages), "UU"), None, None]
    for code, path in st.unstaged:
        if path in rows:
            rows[path][1] = code
        else:
            rows[path] = [" ", code, None]
    out_lines = []
    if branch:
        if st.branch is None:
            out_lines.append("## HEAD (no branch)")
        elif st.head is None:
            out_lines.append("## No commits yet on %s" % st.branch)
        else:
            out_lines.append("## %s" % st.branch)
    root_rel = porcelain
    def fmt(p):
        p = rel(repo, p, full=root_rel)
        if z:
            return p
        q = quote_path(p)
        return '"%s"' % p if q == p and " " in p else q
    for path in sorted(rows, key=fsencode):
        x, y, old = rows[path]
        if y is None:
            xy = x
        else:
            xy = x + y
        if old is not None:
            if z:
                out_lines.append("%s %s\0%s" % (xy, fmt(path), fmt(old)))
            else:
                out_lines.append("%s %s -> %s" % (xy, fmt(old), fmt(path)))
        else:
            out_lines.append("%s %s" % (xy, fmt(path)))
    for p in st.untracked:
        out_lines.append("?? " + fmt(p))
    for p in st.ignored:
        out_lines.append("!! " + fmt(p))
    return out_lines


def run(ctx, args):
    args = expand_short(args, "sbzv")
    short = porcelain = z = branch = False
    untracked = "normal"
    ignored = False
    paths = []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--":
            paths += args[i + 1:]
            break
        if a in ("-s", "--short"):
            short = True
        elif a == "--porcelain" or a.startswith("--porcelain="):
            porcelain = True
        elif a == "--long":
            short = porcelain = False
        elif a in ("-b", "--branch"):
            branch = True
        elif a == "-z":
            z = True
        elif a in ("-u", "--untracked-files"):
            untracked = "all"
        elif a.startswith("--untracked-files="):
            untracked = a.split("=", 1)[1]
        elif a.startswith("-u") and len(a) > 2:
            untracked = a[2:]
        elif a == "--ignored" or a.startswith("--ignored="):
            ignored = True
        elif a in ("-v", "--verbose", "--no-ahead-behind", "--column", "--no-column"):
            pass
        elif a.startswith("-") and a != "-":
            usage_error(unknown_opt_msg(a), USAGE)
        else:
            paths.append(a)
        i += 1
    if untracked not in ("no", "normal", "all"):
        usage_error("Invalid untracked files mode '%s'" % untracked)
    repo = ctx.worktree_repo()
    spec = Pathspec(repo, paths) if paths else None
    st = statuslib.compute(repo, untracked, ignored, spec)
    if spec:
        st.staged = [p for p in st.staged if spec.match(p.new_path) or spec.match(p.old_path)]
        st.unstaged = [(c, p) for c, p in st.unstaged if spec.match(p)]
        st.unmerged = {p: s for p, s in st.unmerged.items() if spec.match(p)}
    if short or porcelain or z:
        lines = short_lines(repo, st, porcelain or z, z, branch)
        term = "\0" if z else "\n"
        for ln in lines:
            out(ln + term)
        return 0
    text, _ = render_long(repo, st, False, untracked)
    out(text)
    return 0
