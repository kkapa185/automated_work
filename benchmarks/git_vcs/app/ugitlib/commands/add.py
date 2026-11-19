"""git add"""
import os
import stat

from ..ignore import IgnoreMatcher
from ..index import Index
from ..pathspec import Pathspec
from ..util import Fatal, err, expand_short, out, usage_error, unknown_opt_msg
from ..worktree import (is_racy, lstat, make_entry, mode_from_stat, stat_matches, trust_filemode,
                        walk_untracked)

USAGE = "git add [<options>] [--] <pathspec>..."


def run(ctx, args):
    args = expand_short(args, "AufnvN")
    all_ = update = force = dry = verbose = False
    paths = []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--":
            paths += args[i + 1:]
            break
        if a in ("-A", "--all", "--no-ignore-removal"):
            all_ = True
        elif a in ("-u", "--update"):
            update = True
        elif a in ("-f", "--force"):
            force = True
        elif a in ("-n", "--dry-run"):
            dry = True
        elif a in ("-v", "--verbose"):
            verbose = True
        elif a == "--ignore-errors":
            pass
        elif a.startswith("-") and a != "-":
            usage_error(unknown_opt_msg(a), USAGE)
        else:
            paths.append(a)
        i += 1
    repo = ctx.worktree_repo()
    if not paths and not (all_ or update):
        err("Nothing specified, nothing added.\n"
            "hint: Maybe you wanted to say 'git add .'?\n"
            "hint: Turn this message off by running\n"
            "hint: \"git config advice.addEmptyPathspec false\"\n")
        return 0
    spec = Pathspec(repo, paths if paths else [":/"])
    index = Index.load(repo)
    ignore = IgnoreMatcher(repo)

    # candidates: tracked paths, then untracked files
    tracked = []
    seen = set()
    for e in index.sorted_entries():
        if e.path not in seen and spec.match(e.path):
            seen.add(e.path)
            tracked.append(e.path)
    untracked = [] if update else walk_untracked(repo, index, ignore, spec,
                                                 "all" if force else "untracked")
    # explicit-path validation
    for item in spec.includes:
        if item.glob:
            ok = any(item.match(p) for p in tracked) or any(item.match(p) for p in untracked)
            if not ok and not update:
                ok = any(item.match(p) for p in walk_untracked(repo, index, ignore, spec, "all"))
        else:
            ok = (item.path == "" or index.has_path(item.path) or index.is_dir(item.path)
                  or lstat(repo, item.path) is not None)
        if not ok:
            if not item.glob:
                common = os.path.commonprefix([i.path for i in spec.includes])
                common = common[:common.rfind("/")] if "/" in common else ""
                parts = common.split("/") if common else []
                if len(parts) >= 2 and os.path.isdir(os.path.join(repo.worktree, parts[0])):
                    parent = os.path.join(repo.worktree, *parts)
                    if not os.path.lexists(parent):
                        err("warning: could not open directory '%s/': No such file or directory\n" % common)
                    elif not os.path.isdir(parent):
                        err("warning: could not open directory '%s/': Not a directory\n" % common)
            raise Fatal("pathspec '%s' did not match any files" % item.orig)

    ignored_hits = []
    if not force and not update:
        for item in spec.includes:
            if item.path and not item.glob and not index.has_path(item.path) \
                    and not index.is_dir(item.path):
                st = lstat(repo, item.path)
                if st is not None and ignore.is_ignored(item.path, stat.S_ISDIR(st.st_mode)):
                    ignored_hits.append(item.path)
    trust = trust_filemode(repo)
    changed = False

    def report(verb, p):
        if verbose or dry:
            out("%s '%s'\n" % (verb, p))

    try:
        for p in tracked:
            ents = index.stages(p)
            e0 = index.get(p, 0)
            st = lstat(repo, p)
            if st is not None and stat.S_ISDIR(st.st_mode) and (e0 is None or e0.mode != 0o160000):
                st = None
            if e0 is not None and e0.mode == 0o160000:
                continue
            if st is None:
                report("remove", p)
                if not dry:
                    index.remove(p)
                    changed = True
                continue
            if e0 is not None and len(ents) == 1:
                if stat_matches(e0, st) and not is_racy(index, e0) and \
                        mode_from_stat(st, trust, e0.mode) == e0.mode:
                    continue
                ne = make_entry(repo, p, st, e0, write=not dry)
                if ne.sha != e0.sha or ne.mode != e0.mode:
                    report("add", p)
                if not dry:
                    index.add(ne)
                    changed = True
            else:
                ne = make_entry(repo, p, st, e0, write=not dry)
                report("add", p)
                if not dry:
                    index.add(ne)
                    changed = True
        for p in untracked:
            st = lstat(repo, p)
            if st is None:
                continue
            ne = make_entry(repo, p, st, None, write=not dry)
            report("add", p)
            if not dry:
                index.add(ne)
                changed = True
    except OSError as e:
        name = getattr(e, "filename", None) or "?"
        rel = os.path.relpath(name, repo.worktree) if os.path.isabs(str(name)) else name
        err("error: open(\"%s\"): %s\nerror: unable to index file '%s'\n" % (rel, e.strerror, rel))
        raise Fatal("adding files failed")
    if changed:
        index.write(repo)
    if ignored_hits:
        err("The following paths are ignored by one of your .gitignore files:\n")
        for h in ignored_hits:
            err(h + "\n")
        err("hint: Use -f if you really want to add them.\n"
            "hint: Turn this message off by running\n"
            "hint: \"git config advice.addIgnoredFile false\"\n")
        return 1
    return 0
