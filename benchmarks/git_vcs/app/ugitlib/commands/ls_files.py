"""git ls-files"""
import posixpath

from ..ignore import IgnoreMatcher
from ..index import Index
from ..pathspec import Pathspec
from ..util import fsencode, out, err, quote_path, usage_error, unknown_opt_msg
from ..worktree import entry_state, walk_untracked, lstat

USAGE = "git ls-files [<options>] [<file>...]"


def run(ctx, args):
    cached = deleted = modified = others = stage = unmerged = ignored = False
    zero = full_name = exclude_std = directory = error_unmatch = False
    no_empty = False
    paths = []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--":
            paths += args[i + 1:]
            break
        if a in ("-c", "--cached"):
            cached = True
        elif a in ("-d", "--deleted"):
            deleted = True
        elif a in ("-m", "--modified"):
            modified = True
        elif a in ("-o", "--others"):
            others = True
        elif a in ("-s", "--stage"):
            stage = True
        elif a in ("-u", "--unmerged"):
            unmerged = True
        elif a in ("-i", "--ignored"):
            ignored = True
        elif a == "-z":
            zero = True
        elif a == "--full-name":
            full_name = True
        elif a == "--exclude-standard":
            exclude_std = True
        elif a == "--directory":
            directory = True
        elif a == "--no-empty-directory":
            no_empty = True
        elif a == "--error-unmatch":
            error_unmatch = True
        elif a.startswith("-") and a != "-":
            usage_error(unknown_opt_msg(a), USAGE)
        else:
            paths.append(a)
        i += 1
    repo = ctx.worktree_repo()
    index = Index.load(repo)
    if not (cached or deleted or modified or others or stage or unmerged or ignored):
        cached = True
    if ignored and not (cached or others):
        cached = True
    spec = Pathspec(repo, paths) if paths else None
    prefix = repo.prefix
    if spec is None and prefix:
        spec = Pathspec(repo, ["."])
    term = "\0" if zero else "\n"

    def show(path):
        if full_name or not prefix:
            shown = path
        else:
            shown = posixpath.relpath(path, prefix.rstrip("/"))
        return shown if zero else quote_path(shown)

    ignore = IgnoreMatcher(repo)
    matched = set()
    lines = []

    if others or (ignored and not cached):
        mode = "untracked"
        if ignored:
            mode = "ignored"
        elif not exclude_std:
            mode = "all"
        if mode == "all" and not exclude_std:
            # without exclude rules every untracked file is listed (ignore rules not applied)
            class NoIgnore:
                def is_ignored(self, p, d=False):
                    return False
            matcher = NoIgnore()
        else:
            matcher = ignore
        if ignored and not exclude_std:
            matcher = ignore  # -i needs the standard rules to be meaningful
        found = walk_untracked(repo, index, matcher, spec, "untracked" if mode == "all" else mode,
                               collapse=directory and not no_empty or directory)
        for p in found:
            lines.append(show(p) + term)
            matched.add(p)

    if cached or stage or unmerged or deleted or modified:
        for e in index.sorted_entries():
            if spec is not None and not spec.match(e.path):
                continue
            if ignored and cached and not ignore.is_ignored(e.path, False):
                continue
            if unmerged and e.stage == 0:
                continue
            if cached or stage or unmerged:
                matched.add(e.path)
                if stage or unmerged:
                    lines.append("%06o %s %d\t%s%s" % (e.mode, e.sha, e.stage, show(e.path), term))
                elif not (deleted or modified) or cached:
                    lines.append(show(e.path) + term)
                    continue
            if (deleted or modified) and e.stage == 0 and not (cached or stage or unmerged):
                state = entry_state(repo, index, e)
                if modified and state != "clean":
                    matched.add(e.path)
                    lines.append(show(e.path) + term)
                if deleted and state == "missing":
                    matched.add(e.path)
                    lines.append(show(e.path) + term)
    for ln in lines:
        out(ln)
    if error_unmatch and spec is not None:
        for item in spec.includes:
            if not any(item.match(p) for p in matched):
                err("error: pathspec '%s' did not match any file(s) known to git\n"
                    "Did you forget to 'git add'?\n" % item.orig)
                return 1
    return 0
