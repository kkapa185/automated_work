"""Commit graph traversal: date-ordered walks, ranges, merge bases."""
import heapq

from .objects import ObjectNotFound


def commit_time(repo, sha):
    c = repo.read_commit(sha)
    parts = c.committer.rsplit(">", 1)[-1].split()
    try:
        return int(parts[0])
    except (IndexError, ValueError):
        return 0


def ancestors(repo, tips, stop=None):
    """Set of all commits reachable from ``tips`` (inclusive)."""
    seen = set()
    stack = list(tips)
    while stack:
        s = stack.pop()
        if s in seen:
            continue
        seen.add(s)
        stack.extend(repo.read_commit(s).parents)
    return seen


def walk(repo, include, exclude=(), first_parent=False, parents_of=None):
    """Yield commit shas newest-first (git's default date order) for ``include`` minus anything
    reachable from ``exclude``.  ``parents_of(sha)`` may override parent lists (history
    simplification)."""
    hidden = ancestors(repo, exclude) if exclude else set()
    heap = []
    seen = set()
    seq = 0

    def push(s):
        nonlocal seq
        if s in seen or s in hidden:
            return
        seen.add(s)
        heapq.heappush(heap, (-commit_time(repo, s), seq, s))
        seq += 1

    for s in include:
        push(s)
    while heap:
        _, _, s = heapq.heappop(heap)
        yield s
        ps = parents_of(s) if parents_of else repo.read_commit(s).parents
        if first_parent:
            ps = ps[:1]
        for p in ps:
            push(p)


def is_ancestor(repo, anc, desc):
    """True if ``anc`` is reachable from ``desc``."""
    if anc == desc:
        return True
    return anc in ancestors(repo, [desc])


def merge_bases(repo, a, b):
    """Best common ancestors of commits a and b."""
    anc_a = ancestors(repo, [a])
    common = []
    seen = set()
    stack = [b]
    while stack:
        s = stack.pop()
        if s in seen:
            continue
        seen.add(s)
        if s in anc_a:
            common.append(s)
            continue  # its ancestors are common but not "best"
        stack.extend(repo.read_commit(s).parents)
    if len(common) <= 1:
        return common
    best = []
    for c in common:
        if not any(o != c and is_ancestor(repo, c, o) for o in common):
            best.append(c)
    return best
