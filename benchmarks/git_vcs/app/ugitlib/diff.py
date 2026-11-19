"""Diff engine: Myers line diff (linear space) with git-style slider compaction, unified hunks,
git patch headers, rename detection and diffstat."""
import math
from collections import Counter

from .objects import hash_object
from .util import fsencode, quote_path

# ----------------------------------------------------------------------------- line diff

def split_lines(data):
    """Split bytes into lines keeping the terminating newline (last line may lack it)."""
    if not data:
        return []
    lines = data.split(b"\n")
    last = lines.pop()
    res = [ln + b"\n" for ln in lines]
    if last:
        res.append(last)
    return res


_LINE_MAX = 1 << 60


def _bogosqrt(n):
    i = 1
    while n > 0:
        n >>= 2
        i <<= 1
    return i


def _split(ha1, off1, lim1, ha2, off2, lim2, kvdf, kvdb, base, mxcost):
    """Find the split point of the box (Myers' bidirectional search, same tie-breaking as xdiff)."""
    dmin, dmax = off1 - lim2, lim1 - off2
    fmid, bmid = off1 - off2, lim1 - lim2
    odd = (fmid - bmid) & 1
    fmin = fmax = fmid
    bmin = bmax = bmid
    kvdf[base + fmid] = off1
    kvdb[base + bmid] = lim1
    ec = 1
    while True:
        if fmin > dmin:
            fmin -= 1
            kvdf[base + fmin - 1] = -1
        else:
            fmin += 1
        if fmax < dmax:
            fmax += 1
            kvdf[base + fmax + 1] = -1
        else:
            fmax -= 1
        d = fmax
        while d >= fmin:
            if kvdf[base + d - 1] >= kvdf[base + d + 1]:
                i1 = kvdf[base + d - 1] + 1
            else:
                i1 = kvdf[base + d + 1]
            i2 = i1 - d
            while i1 < lim1 and i2 < lim2 and ha1[i1] == ha2[i2]:
                i1 += 1
                i2 += 1
            kvdf[base + d] = i1
            if odd and bmin <= d <= bmax and kvdb[base + d] <= i1:
                return i1, i2
            d -= 2
        if bmin > dmin:
            bmin -= 1
            kvdb[base + bmin - 1] = _LINE_MAX
        else:
            bmin += 1
        if bmax < dmax:
            bmax += 1
            kvdb[base + bmax + 1] = _LINE_MAX
        else:
            bmax -= 1
        d = bmax
        while d >= bmin:
            if kvdb[base + d - 1] < kvdb[base + d + 1]:
                i1 = kvdb[base + d - 1]
            else:
                i1 = kvdb[base + d + 1] - 1
            i2 = i1 - d
            while i1 > off1 and i2 > off2 and ha1[i1 - 1] == ha2[i2 - 1]:
                i1 -= 1
                i2 -= 1
            kvdb[base + d] = i1
            if not odd and fmin <= d <= fmax and i1 <= kvdf[base + d]:
                return i1, i2
            d -= 2
        if ec >= mxcost:
            fbest = fbest1 = -1
            d = fmax
            while d >= fmin:
                i1 = min(kvdf[base + d], lim1)
                i2 = i1 - d
                if lim2 < i2:
                    i1, i2 = lim2 + d, lim2
                if fbest < i1 + i2:
                    fbest, fbest1 = i1 + i2, i1
                d -= 2
            bbest = bbest1 = _LINE_MAX
            d = bmax
            while d >= bmin:
                i1 = max(off1, kvdb[base + d])
                i2 = i1 - d
                if i2 < off2:
                    i1, i2 = off2 + d, off2
                if i1 + i2 < bbest:
                    bbest, bbest1 = i1 + i2, i1
                d -= 2
            if (lim1 + lim2) - bbest < fbest:
                return fbest1, fbest - fbest1
            return bbest1, bbest - bbest1
        ec += 1


def _myers(a, b, c1, c2):
    """Mark changed lines of integer sequences a, b (results written to c1/c2 by index)."""
    n1, n2 = len(a), len(b)
    ndiags = n1 + n2 + 3
    mxcost = max(256, _bogosqrt(ndiags))
    base = n2 + 1
    kvdf = [0] * (ndiags + 2)
    kvdb = [0] * (ndiags + 2)
    stack = [(0, n1, 0, n2)]
    while stack:
        off1, lim1, off2, lim2 = stack.pop()
        while off1 < lim1 and off2 < lim2 and a[off1] == b[off2]:
            off1 += 1
            off2 += 1
        while off1 < lim1 and off2 < lim2 and a[lim1 - 1] == b[lim2 - 1]:
            lim1 -= 1
            lim2 -= 1
        if off1 == lim1:
            for j in range(off2, lim2):
                c2[j] = True
        elif off2 == lim2:
            for i in range(off1, lim1):
                c1[i] = True
        else:
            i1, i2 = _split(a, off1, lim1, b, off2, lim2, kvdf, kvdb, base, mxcost)
            if (i1 == off1 and i2 == off2) or (i1 == lim1 and i2 == lim2):
                # no progress (degenerate heuristic split): treat the box as fully changed
                for i in range(off1, lim1):
                    c1[i] = True
                for j in range(off2, lim2):
                    c2[j] = True
                continue
            stack.append((i1, lim1, i2, lim2))
            stack.append((off1, i1, off2, i2))


def _indent(line):
    ret = 0
    for ch in line:
        if ch == 32:
            ret += 1
        elif ch == 9:
            ret += 8 - ret % 8
        elif ch in (10, 13, 11, 12):
            continue
        else:
            return min(ret, 200)
        if ret >= 200:
            return 200
    return -1


_MAX_BLANKS = 20


def _measure(lines, split):
    n = len(lines)
    if split >= n:
        eof, indent = True, -1
    else:
        eof, indent = False, _indent(lines[split])
    pre_blank, pre_indent = 0, -1
    for i in range(split - 1, -1, -1):
        pre_indent = _indent(lines[i])
        if pre_indent != -1:
            break
        pre_blank += 1
        if pre_blank == _MAX_BLANKS:
            pre_indent = 0
            break
    post_blank, post_indent = 0, -1
    for i in range(split + 1, n):
        post_indent = _indent(lines[i])
        if post_indent != -1:
            break
        post_blank += 1
        if post_blank == _MAX_BLANKS:
            post_indent = 0
            break
    return eof, indent, pre_blank, pre_indent, post_blank, post_indent


def _score(lines, split, acc):
    eof, indent, pre_blank, pre_indent, post_blank, post_indent = _measure(lines, split)
    pb = 1 + post_blank if indent == -1 else 0
    total_blank = pre_blank + pb
    pen = 0
    if pre_indent == -1 and pre_blank == 0:
        pen += 1
    if eof:
        pen += 21
    pen += -30 * total_blank
    pen += 6 * pb
    ind = indent if indent != -1 else post_indent
    any_blanks = total_blank != 0
    acc[1] += ind
    if ind == -1 or pre_indent == -1:
        pass
    elif ind > pre_indent:
        pen += 10 if any_blanks else -4
    elif ind == pre_indent:
        pass
    else:
        if post_indent != -1 and post_indent > ind:
            pen += 17 if any_blanks else 24
        else:
            pen += 17 if any_blanks else 23
    acc[0] += pen


def _compact(ids1, ids2, lines1, r1, r2):
    """git's xdl_change_compact with the indent heuristic on side 1 (r = change flags with
    one sentinel cell at each end)."""
    n1, n2 = len(ids1), len(ids2)

    class G:
        pass

    def R(r, i):
        return r[i + 1]

    def init(r):
        g = G()
        g.start = g.end = 0
        while R(r, g.end):
            g.end += 1
        return g

    def nxt(r, g, n):
        g.start = g.end + 1
        g.end = g.start
        while g.end < n + 1 and R(r, g.end):
            g.end += 1
        return g.start > n

    def prev(r, g):
        g.end = g.start - 1
        g.start = g.end
        while g.start - 1 >= -1 and R(r, g.start - 1):
            g.start -= 1
        return g.end < 0

    def up(r, ids, g):
        if g.start > 0 and ids[g.start - 1] == ids[g.end - 1]:
            g.start -= 1
            r[g.start + 1] = 1
            g.end -= 1
            r[g.end + 1] = 0
            while R(r, g.start - 1):
                g.start -= 1
            return False
        return True

    def down(r, ids, n, g):
        if g.end < n and ids[g.start] == ids[g.end]:
            r[g.start + 1] = 0
            g.start += 1
            r[g.end + 1] = 1
            g.end += 1
            while R(r, g.end):
                g.end += 1
            return False
        return True

    g = init(r1)
    go = init(r2)
    while True:
        if g.end != g.start:
            while True:
                groupsize = g.end - g.start
                end_matching_other = -1
                while not up(r1, ids1, g):
                    if prev(r2, go):
                        break
                earliest_end = g.end
                if go.end > go.start:
                    end_matching_other = g.end
                while True:
                    if down(r1, ids1, n1, g):
                        break
                    if nxt(r2, go, n2):
                        break
                    if go.end > go.start:
                        end_matching_other = g.end
                if groupsize == g.end - g.start:
                    break
            if g.end == earliest_end:
                pass
            elif end_matching_other != -1:
                while go.end == go.start:
                    if up(r1, ids1, g):
                        break
                    if prev(r2, go):
                        break
            else:
                shift = earliest_end
                if g.end - groupsize - 1 > shift:
                    shift = g.end - groupsize - 1
                if g.end - 100 > shift:
                    shift = g.end - 100
                best_shift, best = -1, None
                while shift <= g.end:
                    acc = [0, 0]
                    _score(lines1, shift, acc)
                    _score(lines1, shift - groupsize, acc)
                    if best is None:
                        take = True
                    else:
                        cmp_ind = (acc[1] > best[1]) - (acc[1] < best[1])
                        take = 60 * cmp_ind + (acc[0] - best[0]) <= 0
                    if take:
                        best, best_shift = acc, shift
                    shift += 1
                while g.end > best_shift:
                    if up(r1, ids1, g):
                        break
                    if prev(r2, go):
                        break
        if nxt(r1, g, n1):
            break
        nxt(r2, go, n2)


def diff_changes(lines1, lines2):
    """Return (chg1, chg2): per-line booleans marking deleted / inserted lines."""
    table = {}
    ids1 = [table.setdefault(ln, len(table)) for ln in lines1]
    ids2 = [table.setdefault(ln, len(table)) for ln in lines2]
    n1, n2 = len(ids1), len(ids2)
    c1 = [False] * n1
    c2 = [False] * n2
    lo = 0
    while lo < n1 and lo < n2 and ids1[lo] == ids2[lo]:
        lo += 1
    h1, h2 = n1, n2
    while h1 > lo and h2 > lo and ids1[h1 - 1] == ids2[h2 - 1]:
        h1 -= 1
        h2 -= 1
    if lo < h1 or lo < h2:
        cnt1 = Counter(ids1)   # git counts occurrences over the whole files (incl. trimmed ends)
        cnt2 = Counter(ids2)
        keep1 = [i for i in range(lo, h1) if cnt2.get(ids1[i])]
        keep2 = [j for j in range(lo, h2) if cnt1.get(ids2[j])]
        k1 = set(keep1)
        k2 = set(keep2)
        for i in range(lo, h1):
            if i not in k1:
                c1[i] = True
        for j in range(lo, h2):
            if j not in k2:
                c2[j] = True
        a = [ids1[i] for i in keep1]
        b = [ids2[j] for j in keep2]
        ra = [False] * len(a)
        rb = [False] * len(b)
        _myers(a, b, ra, rb)
        for idx, ch in enumerate(ra):
            if ch:
                c1[keep1[idx]] = True
        for idx, ch in enumerate(rb):
            if ch:
                c2[keep2[idx]] = True
    r1 = [0] + [1 if x else 0 for x in c1] + [0]
    r2 = [0] + [1 if x else 0 for x in c2] + [0]
    if any(c1) or any(c2):
        _compact(ids1, ids2, lines1, r1, r2)
        _compact(ids2, ids1, lines2, r2, r1)
    return [bool(x) for x in r1[1:-1]], [bool(x) for x in r2[1:-1]]


def change_groups(chg1, chg2):
    groups = []
    i = j = 0
    n1, n2 = len(chg1), len(chg2)
    while i < n1 or j < n2:
        if i < n1 and j < n2 and not chg1[i] and not chg2[j]:
            i += 1
            j += 1
            continue
        s1, s2 = i, j
        while i < n1 and chg1[i]:
            i += 1
        while j < n2 and chg2[j]:
            j += 1
        if i == s1 and j == s2:  # safety: should not happen
            i += 1
            j += 1
            continue
        groups.append((s1, i - s1, s2, j - s2))
    return groups


def _funcline(lines, start, limit):
    l = start
    while l != limit and l >= 0:
        ln = lines[l]
        if ln and (ln[:1].isalpha() or ln[:1] in (b"_", b"$")) and ln[0] < 128:
            return ln.rstrip(b"\r\n \t\f\v")[:80]
        l -= 1
    return None


def _range(start, length):
    if length == 1:
        return b"%d" % (start + 1)
    if length == 0:
        return b"%d,0" % start
    return b"%d,%d" % (start + 1, length)


def unified_hunks(lines1, lines2, ctx=3, groups=None):
    """Return list of hunk byte strings (header + body) for the two line lists."""
    if groups is None:
        c1, c2 = diff_changes(lines1, lines2)
        groups = change_groups(c1, c2)
    n1, n2 = len(lines1), len(lines2)
    hunks = []
    k = 0
    funcprev = -1
    while k < len(groups):
        first = k
        while k + 1 < len(groups):
            pg, ng = groups[k], groups[k + 1]
            if ng[0] - (pg[0] + pg[1]) > 2 * ctx:
                break
            k += 1
        last = k
        k += 1
        g0, gl = groups[first], groups[last]
        s1 = max(g0[0] - ctx, 0)
        s2 = max(g0[2] - ctx, 0)
        e1 = min(gl[0] + gl[1] + ctx, n1)
        e2 = min(gl[2] + gl[3] + ctx, n2)
        fn = _funcline(lines1, s1 - 1, funcprev)
        funcprev = s1 - 1
        head = b"@@ -%s +%s @@" % (_range(s1, e1 - s1), _range(s2, e2 - s2))
        if fn:
            head += b" " + fn
        out = [head + b"\n"]

        def emit(prefix, ln):
            out.append(prefix + ln)
            if not ln.endswith(b"\n"):
                out.append(b"\n\\ No newline at end of file\n")

        pos = s1
        for gi in range(first, last + 1):
            i1, c1n, i2, c2n = groups[gi]
            for x in range(pos, i1):
                emit(b" ", lines1[x])
            for x in range(i1, i1 + c1n):
                emit(b"-", lines1[x])
            for x in range(i2, i2 + c2n):
                emit(b"+", lines2[x])
            pos = i1 + c1n
        for x in range(pos, e1):
            emit(b" ", lines1[x])
        hunks.append(b"".join(out))
    return hunks


def count_changes(data1, data2):
    c1, c2 = diff_changes(split_lines(data1), split_lines(data2))
    return sum(c2), sum(c1)  # added, deleted


# ----------------------------------------------------------------------------- file pairs

def is_binary(data):
    return b"\0" in data[:8000]


class Side:
    """One side of a file comparison: mode + blob id + lazy content."""
    __slots__ = ("mode", "_sha", "_data", "loader")

    def __init__(self, mode, sha=None, data=None, loader=None):
        self.mode = mode
        self._sha = sha
        self._data = data
        self.loader = loader

    def data(self):
        if self._data is None:
            self._data = self.loader()
        return self._data

    @property
    def sha(self):
        if self._sha is None:
            self._sha = hash_object("blob", self.data())
        return self._sha


class Pair:
    __slots__ = ("old_path", "new_path", "old", "new", "status", "score")

    def __init__(self, old_path, new_path, old, new, status, score=0):
        self.old_path, self.new_path, self.old, self.new = old_path, new_path, old, new
        self.status, self.score = status, score

    @property
    def path(self):
        return self.new_path if self.new is not None else self.old_path


def blob_side(repo, mode, sha):
    return Side(mode, sha, loader=lambda: repo.odb.read(sha)[1])


def _type(mode):
    return mode & 0o170000


def maps_to_pairs(repo, left, right):
    """left/right: {path: Side}. Returns pairs sorted by path; type changes become D + A."""
    pairs = []
    for path in sorted(set(left) | set(right), key=fsencode):
        a, b = left.get(path), right.get(path)
        if a is not None and b is not None:
            if a.mode == b.mode and a.sha == b.sha:
                continue
            if _type(a.mode) != _type(b.mode):
                pairs.append(Pair(path, path, a, b, "T"))
            else:
                pairs.append(Pair(path, path, a, b, "M"))
        elif a is not None:
            pairs.append(Pair(path, path, a, None, "D"))
        else:
            pairs.append(Pair(path, path, None, b, "A"))
    return pairs


def tree_sides(repo, flat):
    return {p: blob_side(repo, m, s) for p, (m, s) in flat.items()}


# ----------------------------------------------------------------------------- renames

MAX_SCORE = 60000


def _spans(data):
    spans = Counter()
    h = 0
    n = 0
    text = b"\0" not in data[:8000]
    i, L = 0, len(data)
    start = 0
    buf = []
    for i in range(L):
        c = data[i]
        if text and c == 13 and i + 1 < L and data[i + 1] == 10:
            continue
        buf.append(c)
        n += 1
        if c == 10 or n >= 64:
            spans[bytes(buf)] += len(buf)
            buf = []
            n = 0
    if buf:
        spans[bytes(buf)] += len(buf)
    return spans


def similarity(src_data, dst_data):
    max_size = max(len(src_data), len(dst_data))
    if max_size == 0:
        return MAX_SCORE
    if min(len(src_data), len(dst_data)) == 0:
        return 0
    s, d = _spans(src_data), _spans(dst_data)
    copied = 0
    for k, v in s.items():
        dv = d.get(k)
        if dv:
            copied += min(v, dv)
    return copied * MAX_SCORE // max_size


def detect_renames(pairs, threshold=30000, limit=1000):
    """Pair up deleted/added files as renames (exact first, then >= 50% similar)."""
    dels = [p for p in pairs if p.status == "D"]
    adds = [p for p in pairs if p.status == "A"]
    if not dels or not adds:
        return pairs
    used_src = set()
    renamed = {}  # id(add pair) -> (del pair, score)

    def base(p):
        return p.path.rsplit("/", 1)[-1]

    for a in adds:
        if _type(a.new.mode) == 0o160000:
            continue
        cands = [d for d in dels if id(d) not in used_src and d.old.sha == a.new.sha
                 and _type(d.old.mode) == _type(a.new.mode)]
        if cands:
            same = [d for d in cands if base(d) == base(a)]
            d = (same or cands)[0]
            used_src.add(id(d))
            renamed[id(a)] = (d, MAX_SCORE)
    rest_adds = [a for a in adds if id(a) not in renamed and _type(a.new.mode) != 0o160000]
    rest_dels = [d for d in dels if id(d) not in used_src and _type(d.old.mode) != 0o160000]
    if rest_adds and rest_dels and len(rest_adds) * len(rest_dels) <= limit * limit:
        cache = {}

        def data_of(side):
            k = id(side)
            if k not in cache:
                cache[k] = side.data()
            return cache[k]

        scored = []
        for a in rest_adds:
            ad = data_of(a.new)
            for d in rest_dels:
                if _type(d.old.mode) != _type(a.new.mode):
                    continue
                dd = data_of(d.old)
                mx = max(len(ad), len(dd))
                if mx == 0 or abs(len(ad) - len(dd)) * MAX_SCORE > mx * (MAX_SCORE - threshold):
                    continue
                sc = similarity(dd, ad)
                if sc >= threshold:
                    scored.append((-sc, -(1 if base(d) == base(a) else 0), a, d))
        scored.sort(key=lambda t: (t[0], t[1]))
        used_dst = set()
        for nsc, _, a, d in scored:
            if id(a) in used_dst or id(d) in used_src:
                continue
            used_dst.add(id(a))
            used_src.add(id(d))
            renamed[id(a)] = (d, -nsc)
    if not renamed:
        return pairs
    result = []
    for p in pairs:
        if p.status == "D" and id(p) in used_src:
            continue
        if p.status == "A" and id(p) in renamed:
            d, sc = renamed[id(p)]
            result.append(Pair(d.old_path, p.new_path, d.old, p.new, "R", sc))
        else:
            result.append(p)
    return result


# ----------------------------------------------------------------------------- patch output

def _abbrev(repo, sha, minlen):
    return repo.odb.shorten(sha, minlen)


def _name(prefix, path):
    q = quote_path(prefix + path)
    return q


def format_patch(repo, pair, ctx=3):
    """Full git-style diff text (bytes) for a pair."""
    minlen = repo.odb.default_abbrev()
    zero = "0" * minlen
    old, new = pair.old, pair.new
    o_name, n_name = _name("a/", pair.old_path), _name("b/", pair.new_path)
    if pair.status == "T":
        return (format_patch(repo, Pair(pair.old_path, pair.old_path, pair.old, None, "D"), ctx)
                + format_patch(repo, Pair(pair.new_path, pair.new_path, None, pair.new, "A"), ctx))
    out = [("diff --git %s %s\n" % (o_name, n_name)).encode("utf-8", "surrogateescape")]
    status = pair.status
    show_body = True
    if status == "A":
        out.append(b"new file mode %o\n" % new.mode)
        out.append(("index %s..%s\n" % (zero, _abbrev(repo, new.sha, minlen))).encode())
    elif status == "D":
        out.append(b"deleted file mode %o\n" % old.mode)
        out.append(("index %s..%s\n" % (_abbrev(repo, old.sha, minlen), zero)).encode())
    else:
        if old.mode != new.mode:
            out.append(b"old mode %o\nnew mode %o\n" % (old.mode, new.mode))
        if status == "R":
            out.append(("similarity index %d%%\nrename from %s\nrename to %s\n" % (
                pair.score * 100 // MAX_SCORE, quote_path(pair.old_path),
                quote_path(pair.new_path))).encode("utf-8", "surrogateescape"))
        if old.sha != new.sha:
            idx = "index %s..%s" % (_abbrev(repo, old.sha, minlen), _abbrev(repo, new.sha, minlen))
            if old.mode == new.mode:
                idx += " %o" % old.mode
            out.append((idx + "\n").encode())
        else:
            show_body = False
    if not show_body:
        return b"".join(out)
    od = old.data() if old is not None else b""
    nd = new.data() if new is not None else b""
    if not od and not nd:
        return b"".join(out)
    tab = lambda s: s + ("\t" if " " in s else "")
    of = "/dev/null" if old is None else tab(o_name)
    nf = "/dev/null" if new is None else tab(n_name)
    if is_binary(od) or is_binary(nd):
        out.append(("Binary files %s and %s differ\n" % (
            "/dev/null" if old is None else o_name, "/dev/null" if new is None else n_name)
        ).encode("utf-8", "surrogateescape"))
        return b"".join(out)
    out.append(("--- %s\n+++ %s\n" % (of, nf)).encode("utf-8", "surrogateescape"))
    out.extend(unified_hunks(split_lines(od), split_lines(nd), ctx))
    return b"".join(out)


def format_patches(repo, pairs, ctx=3):
    return b"".join(format_patch(repo, p, ctx) for p in pairs)


# ----------------------------------------------------------------------------- stat

def pprint_rename(a, b):
    pfx = 0
    for i, (ca, cb) in enumerate(zip(a, b)):
        if ca != cb:
            break
        if ca == "/":
            pfx = i + 1
    ia, ib = len(a), len(b)
    sfx = 0
    while ia > pfx - 1 and ib > pfx - 1 and ia > 0 and ib > 0 and a[ia - 1] == b[ib - 1]:
        if a[ia - 1] == "/":
            sfx = len(a) - (ia - 1)
        ia -= 1
        ib -= 1
    a_mid = a[pfx:len(a) - sfx] if len(a) - sfx > pfx else ""
    b_mid = b[pfx:len(b) - sfx] if len(b) - sfx > pfx else ""
    if pfx or sfx:
        return "%s{%s => %s}%s" % (a[:pfx], a_mid, b_mid, a[len(a) - sfx:] if sfx else "")
    return "%s => %s" % (a, b)


def pair_display_name(p):
    if p.status == "R":
        return pprint_rename(quote_path(p.old_path), quote_path(p.new_path))
    return quote_path(p.path)


def pair_numstat(p):
    """(added, deleted) or None for binary."""
    od = p.old.data() if p.old is not None else b""
    nd = p.new.data() if p.new is not None else b""
    if is_binary(od) or is_binary(nd):
        return None
    if p.status == "R" and p.old.sha == p.new.sha:
        return 0, 0
    return count_changes(od, nd)


def _scale(it, width, max_change):
    if not it:
        return 0
    return 1 + (it * (width - 1) // max_change)


def format_stat(pairs, width=80):
    """Return (text, files, insertions, deletions) for ``diff --stat``."""
    rows = []
    for p in pairs:
        ns = pair_numstat(p)
        rows.append((pair_display_name(p), ns, p))
    if not rows:
        return "", 0, 0, 0
    max_len = max(len(r[0]) for r in rows)
    max_change = 0
    for name, ns, p in rows:
        if ns is not None:
            max_change = max(max_change, ns[0] + ns[1])
    number_width = max(len(str(max_change)), 3 if any(r[1] is None for r in rows) else 0)
    name_width, graph_width = max_len, max_change
    if name_width + number_width + 6 + graph_width > width:
        if graph_width > width * 3 // 8 - number_width - 6:
            graph_width = max(width * 3 // 8 - number_width - 6, 6)
        if name_width > width - number_width - 6 - graph_width:
            name_width = width - number_width - 6 - graph_width
        else:
            graph_width = width - number_width - 6 - name_width
    lines = []
    ins = dele = 0
    for name, ns, p in rows:
        shown = name
        if len(shown) > name_width:
            shown = shown[len(shown) - name_width + 3:]
            slash = shown.find("/")
            if slash >= 0:
                shown = shown[slash:]
            shown = "..." + shown
        pad = " " * max(name_width - len(shown), 0)
        if ns is None:
            osz = len(p.old.data()) if p.old is not None else 0
            nsz = len(p.new.data()) if p.new is not None else 0
            lines.append(" %s%s | %*s %d -> %d bytes\n" % (shown, pad, number_width, "Bin", osz, nsz))
            continue
        add, dl = ns
        ins += add
        dele += dl
        total = add + dl
        if graph_width <= max_change and max_change > 0:
            t = _scale(total, graph_width, max_change)
            if t < 2 and add and dl:
                t = 2
            if add < dl:
                add = _scale(add, graph_width, max_change)
                dl = t - add
            else:
                dl = _scale(dl, graph_width, max_change)
                add = t - dl
        graph = "+" * add + "-" * dl
        lines.append(" %s%s | %*d%s\n" % (shown, pad, number_width, total, " " + graph if graph else ""))
    return "".join(lines), len(rows), ins, dele


def stat_summary_line(files, ins, dele):
    s = " %d file%s changed" % (files, "" if files == 1 else "s")
    if ins or dele == 0:
        s += ", %d insertion%s(+)" % (ins, "" if ins == 1 else "s")
    if dele or ins == 0:
        s += ", %d deletion%s(-)" % (dele, "" if dele == 1 else "s")
    return s + "\n"


def format_stat_full(pairs):
    text, files, ins, dele = format_stat(pairs)
    if not files:
        return ""
    return text + stat_summary_line(files, ins, dele)


def summary_lines(pairs):
    """' create mode ...' style lines used after diffstat in commit/merge output."""
    out = []
    for p in pairs:
        if p.status == "A":
            out.append(" create mode %06o %s\n" % (p.new.mode, quote_path(p.path)))
        elif p.status == "D":
            out.append(" delete mode %06o %s\n" % (p.old.mode, quote_path(p.path)))
        elif p.status == "R":
            out.append(" rename %s (%d%%)\n" % (pprint_rename(quote_path(p.old_path), quote_path(p.new_path)),
                                                 p.score * 100 // MAX_SCORE))
            if p.old.mode != p.new.mode:
                out.append(" mode change %06o => %06o\n" % (p.old.mode, p.new.mode))
        elif p.status in ("M", "T") and p.old.mode != p.new.mode:
            out.append(" mode change %06o => %06o %s\n" % (p.old.mode, p.new.mode, quote_path(p.path)))
    return "".join(out)
