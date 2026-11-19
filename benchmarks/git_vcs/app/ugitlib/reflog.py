"""Reflog writing/reading (logs/HEAD and logs/refs/heads/*), and 'detached from' lookup."""
import os

from .ident import get_ident
from .util import fsdecode, fsencode

ZERO = "0" * 40


def _tracked(refname):
    return refname == "HEAD" or refname.startswith(("refs/heads/", "refs/remotes/", "refs/notes/"))


def append(repo, refname, old, new, msg):
    """Append one reflog line for ``refname`` (honours core.logAllRefUpdates=false)."""
    if repo.config.get("core.logallrefupdates") is not None and \
            repo.config.get("core.logallrefupdates", "").lower() in ("false", "no", "off", "0"):
        return
    if repo.bare and repo.config.get("core.logallrefupdates") is None:
        return
    if not _tracked(refname):
        return
    ident = get_ident("COMMITTER", repo.config, repo.env, strict=False)
    path = os.path.join(repo.gitdir, "logs", refname)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    line = "%s %s %s\t%s\n" % (old or ZERO, new or ZERO, ident, msg.replace("\n", " "))
    with open(path, "ab") as f:
        f.write(fsencode(line))


def append_raw(repo, refname, old, new, ident, msg):
    path = os.path.join(repo.gitdir, "logs", refname)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "ab") as f:
        f.write(fsencode("%s %s %s\t%s\n" % (old, new, ident, msg)))


def read(repo, refname):
    """List of (old, new, ident, message) oldest first."""
    path = os.path.join(repo.gitdir, "logs", refname)
    try:
        with open(path, "rb") as f:
            text = fsdecode(f.read())
    except OSError:
        return []
    res = []
    for line in text.split("\n"):
        if not line:
            continue
        head, _, msg = line.partition("\t")
        old, new, ident = head[:40], head[41:81], head[82:]
        res.append((old, new, ident, msg))
    return res


def remove(repo, refname):
    try:
        os.unlink(os.path.join(repo.gitdir, "logs", refname))
    except OSError:
        pass
    d = os.path.dirname(os.path.join(repo.gitdir, "logs", refname))
    stop = os.path.join(repo.gitdir, "logs", "refs")
    while d.startswith(stop) and d != stop:
        try:
            os.rmdir(d)
        except OSError:
            break
        d = os.path.dirname(d)


def previous_checkout(repo):
    """The 'from' part of the most recent 'checkout: moving from X to Y' entry (branch name or sha)."""
    for old, new, ident, msg in reversed(read(repo, "HEAD")):
        if msg.startswith("checkout: moving from ") and " to " in msg:
            return msg[len("checkout: moving from "):].rsplit(" to ", 1)[0]
    return None


def detached_from(repo):
    """('at'|'from', label) for a detached HEAD using the checkout reflog, or None."""
    head = repo.head_sha()
    for old, new, ident, msg in reversed(read(repo, "HEAD")):
        if msg.startswith("checkout: moving from ") and " to " in msg:
            target = msg.rsplit(" to ", 1)[1]
            sha = new if new and new != ZERO else None
            if sha is None:
                return None
            label = None
            full = repo.dwim_ref(target)
            if full is not None and repo.refs.resolve(full) != sha:
                full = None
            if full is not None and not (len(target) == 40):
                for pfx in ("refs/tags/", "refs/remotes/"):
                    if full.startswith(pfx):
                        label = full[len(pfx):]
                        break
                else:
                    if full.startswith("refs/heads/"):
                        label = full  # git keeps the full name for local branches
            if label is None:
                label = repo.odb.shorten(sha)
            return ("at" if sha == head else "from", label)
    return None
