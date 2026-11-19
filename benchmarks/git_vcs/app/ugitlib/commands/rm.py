"""git rm"""
import os

from ..index import Index, head_tree_map
from ..pathspec import Pathspec
from ..util import Fatal, err, expand_short, out, usage_error, unknown_opt_msg
from ..worktree import entry_state, lstat

USAGE = "git rm [<options>] [--] <file>..."


def _report(title_sing, title_plur, files, footer):
    if not files:
        return
    err("error: the following %s:\n" % (title_sing if len(files) == 1 else title_plur))
    for f in files:
        err("    %s\n" % f)
    err(footer + "\n")


def run(ctx, args):
    args = expand_short(args, "rfnq")
    force = dry = cached = recursive = quiet = unmatch = False
    paths = []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--":
            paths += args[i + 1:]
            break
        if a in ("-f", "--force"):
            force = True
        elif a in ("-n", "--dry-run"):
            dry = True
        elif a == "--cached":
            cached = True
        elif a in ("-r",):
            recursive = True
        elif a in ("-q", "--quiet"):
            quiet = True
        elif a == "--ignore-unmatch":
            unmatch = True
        elif a.startswith("-") and a != "-":
            usage_error(unknown_opt_msg(a), USAGE)
        else:
            paths.append(a)
        i += 1
    if not paths:
        raise Fatal("No pathspec was given. Which files should I remove?")
    repo = ctx.worktree_repo()
    spec = Pathspec(repo, paths)
    index = Index.load(repo)
    victims = []
    seen = set()
    for e in index.sorted_entries():
        if e.path not in seen and spec.match(e.path):
            seen.add(e.path)
            victims.append(e.path)
    for item in spec.includes:
        if not any(item.match(p) for p in victims):
            if unmatch:
                continue
            raise Fatal("pathspec '%s' did not match any files" % item.orig)
    if not recursive:
        for item in spec.includes:
            if item.path and not item.glob and index.is_dir(item.path) and not index.has_path(item.path):
                raise Fatal("not removing '%s' recursively without -r" % item.path)
    if not force:
        head = head_tree_map(repo)
        local, staged, both = [], [], []
        for p in victims:
            e = index.get(p, 0)
            if e is None:
                continue
            st = lstat(repo, p)
            if st is None:
                continue
            local_changes = entry_state(repo, index, e) != "clean"
            h = head.get(p)
            staged_changes = h is None or h != (e.mode, e.sha)
            if local_changes and staged_changes:
                both.append(p)
            elif not cached:
                if staged_changes:
                    staged.append(p)
                if local_changes:
                    local.append(p)
        if both or staged or local:
            _report("file has staged content different from both the\nfile and the HEAD",
                    "files have staged content different from both the\nfile and the HEAD", both,
                    "(use -f to force removal)")
            foot = "(use --cached to keep the file, or -f to force removal)"
            _report("file has changes staged in the index", "files have changes staged in the index",
                    staged, foot)
            _report("file has local modifications", "files have local modifications", local, foot)
            return 1
    for p in victims:
        if not quiet:
            out("rm '%s'\n" % p)
    if dry:
        return 0
    for p in victims:
        index.remove(p)
        if not cached:
            full = os.path.join(repo.worktree, p)
            try:
                os.unlink(full)
            except OSError:
                pass
            d = os.path.dirname(full)
            while d != repo.worktree and d.startswith(repo.worktree):
                try:
                    os.rmdir(d)
                except OSError:
                    break
                d = os.path.dirname(d)
    index.write(repo)
    return 0
