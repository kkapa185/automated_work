"""Three-way merge: line-level (diff3, "zealous" conflict refinement) and tree-level."""
from . import diff as D
from .objects import hash_object
from .util import fsencode


def _hunks(base, other):
    c1, c2 = D.diff_changes(base, other)
    return D.change_groups(c1, c2)  # (base_start, base_len, other_start, other_len)


def _apply(base, other, members, s, e):
    """Text of base[s:e] after applying ``members`` (hunks of one side)."""
    res = []
    pos = s
    for i1, n1, i2, n2 in members:
        res.extend(base[pos:i1])
        res.extend(other[i2:i2 + n2])
        pos = i1 + n1
    res.extend(base[pos:e])
    return res


def _terminated(lines):
    if lines and not lines[-1].endswith(b"\n"):
        return lines[:-1] + [lines[-1] + b"\n"]
    return lines


def merge_text(base, ours, theirs, ours_label, theirs_label, marker=7):
    """Merge three line lists. Returns (output_lines, conflict_count)."""
    h1 = _hunks(base, ours)
    h2 = _hunks(base, theirs)
    out = []
    conflicts = 0
    pos = 0
    i = j = 0
    lm = b"<" * marker + b" " + ours_label + b"\n"
    mm = b"=" * marker + b"\n"
    rm = b">" * marker + b" " + theirs_label + b"\n"
    while i < len(h1) or j < len(h2):
        # pick the next hunk (earliest base start)
        if j >= len(h2) or (i < len(h1) and h1[i][0] <= h2[j][0]):
            side, h = 1, h1[i]
        else:
            side, h = 2, h2[j]
        start, end = h[0], h[0] + h[1]
        m1, m2 = [], []
        (m1 if side == 1 else m2).append(h)
        if side == 1:
            i += 1
        else:
            j += 1
        # grow the cluster with every hunk that overlaps or touches it
        grown = True
        while grown:
            grown = False
            if i < len(h1) and h1[i][0] <= end:
                m1.append(h1[i])
                end = max(end, h1[i][0] + h1[i][1])
                i += 1
                grown = True
            if j < len(h2) and h2[j][0] <= end:
                m2.append(h2[j])
                end = max(end, h2[j][0] + h2[j][1])
                j += 1
                grown = True
        out.extend(base[pos:start])
        pos = end
        if not m2:
            out.extend(_apply(base, ours, m1, start, end))
            continue
        if not m1:
            out.extend(_apply(base, theirs, m2, start, end))
            continue
        a = _apply(base, ours, m1, start, end)
        b = _apply(base, theirs, m2, start, end)
        if a == b:
            out.extend(a)
            continue
        if a and b:
            # zealous refinement: lines both sides agree on are moved out of the conflict
            c1, c2 = D.diff_changes(a, b)
            groups = D.change_groups(c1, c2)
            p = 0
            for g1, n1, g2, n2 in groups:
                out.extend(a[p:g1])
                out.append(lm)
                out.extend(_terminated(a[g1:g1 + n1]))
                out.append(mm)
                out.extend(_terminated(b[g2:g2 + n2]))
                out.append(rm)
                conflicts += 1
                p = g1 + n1
            out.extend(a[p:])
        else:
            out.append(lm)
            out.extend(_terminated(a))
            out.append(mm)
            out.extend(_terminated(b))
            out.append(rm)
            conflicts += 1
    out.extend(base[pos:])
    return out, conflicts


class TreeMergeResult:
    def __init__(self):
        self.clean = {}        # path -> (mode, sha)   resolved entries
        self.conflicts = {}    # path -> {stage: (mode, sha)}
        self.worktree = {}     # path -> (mode, bytes) content to write for conflicted paths
        self.messages = []     # (stdout lines) in git's order
        self.errors = []       # (stderr lines)


def odb_read(repo, entry):
    return repo.odb.read(entry[1])[1]


def _mode_merge(b, o, t):
    """Return merged mode or None on conflict."""
    if o == t:
        return o
    if o == b:
        return t
    if t == b:
        return o
    return None


def merge_trees(repo, base, ours, theirs, ours_label, theirs_label, write_blobs=True):
    """Merge flat tree maps {path: (mode, sha)}. No rename detection."""
    res = TreeMergeResult()
    paths = sorted(set(base) | set(ours) | set(theirs), key=fsencode)
    for p in paths:
        b, o, t = base.get(p), ours.get(p), theirs.get(p)
        if o == t:
            if o is not None:
                res.clean[p] = o
            continue
        if b == o:
            if t is not None:
                res.clean[p] = t
            continue
        if b == t:
            if o is not None:
                res.clean[p] = o
            continue
        if o is not None and t is not None:
            _merge_both_present(repo, res, p, b, o, t, ours_label, theirs_label)
        else:
            # modify/delete
            if o is None:
                res.conflicts[p] = {s: v for s, v in ((1, b), (3, t)) if v is not None}
                res.worktree[p] = (t[0], odb_read(repo, t))
                res.messages.append(
                    "CONFLICT (modify/delete): %s deleted in %s and modified in %s.  Version %s of %s "
                    "left in tree." % (p, ours_label.decode("utf-8", "replace"),
                                       theirs_label.decode("utf-8", "replace"),
                                       theirs_label.decode("utf-8", "replace"), p))
            else:
                res.conflicts[p] = {s: v for s, v in ((1, b), (2, o)) if v is not None}
                res.worktree[p] = (o[0], odb_read(repo, o))
                res.messages.append(
                    "CONFLICT (modify/delete): %s deleted in %s and modified in %s.  Version %s of %s "
                    "left in tree." % (p, theirs_label.decode("utf-8", "replace"),
                                       ours_label.decode("utf-8", "replace"),
                                       ours_label.decode("utf-8", "replace"), p))
    return res


def _is_binary(data):
    return b"\0" in data[:8000]


def _merge_both_present(repo, res, p, b, o, t, ol, tl):
    odb = repo.odb
    mode = _mode_merge(b[0] if b else None, o[0], t[0])
    odata = odb.read(o[1])[1]
    tdata = odb.read(t[1])[1]
    bdata = odb.read(b[1])[1] if b else b""
    ostr, tstr = ol.decode("utf-8", "replace"), tl.decode("utf-8", "replace")
    kind = "content" if b else "add/add"
    symlink = (o[0] & 0o170000) == 0o120000 or (t[0] & 0o170000) == 0o120000
    binary = _is_binary(odata) or _is_binary(tdata) or _is_binary(bdata) or symlink
    if binary:
        res.messages.append("warning: Cannot merge binary files: %s (%s vs. %s)" % (p, ostr, tstr))
    res.messages.append("Auto-merging %s" % p)
    if binary:
        stages = {2: o, 3: t}
        if b:
            stages[1] = b
        res.conflicts[p] = dict(sorted(stages.items()))
        res.worktree[p] = (o[0], odata)
        res.messages.append("CONFLICT (%s): Merge conflict in %s" % (kind, p))
        return
    lines, nconf = merge_text(D.split_lines(bdata), D.split_lines(odata), D.split_lines(tdata), ol, tl)
    data = b"".join(lines)
    if nconf or mode is None:
        stages = {2: o, 3: t}
        if b:
            stages[1] = b
        res.conflicts[p] = dict(sorted(stages.items()))
        res.worktree[p] = (o[0] if mode is None else mode, data)
        res.messages.append("CONFLICT (%s): Merge conflict in %s" % (kind, p))
        return
    sha = odb.write("blob", data)
    res.clean[p] = (mode, sha)
