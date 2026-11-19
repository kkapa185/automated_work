"""Commit formatting: log/show default formats, --format placeholders, date formats."""
import re

from .ident import DAYS, MONTHS, format_date, format_tz, parse_tz
from .objects import parse_ident

import time


def format_date_style(ts, tz_str, style="default"):
    tz = parse_tz(tz_str)
    t = time.gmtime(ts + tz * 60)
    if style in ("default", "", None):
        return format_date(ts, tz)
    if style in ("iso", "iso8601"):
        return "%04d-%02d-%02d %02d:%02d:%02d %s" % (t.tm_year, t.tm_mon, t.tm_mday, t.tm_hour,
                                                    t.tm_min, t.tm_sec, tz_str)
    if style in ("iso-strict", "iso8601-strict"):
        z = "%s:%s" % (tz_str[:3], tz_str[3:])
        return "%04d-%02d-%02dT%02d:%02d:%02d%s" % (t.tm_year, t.tm_mon, t.tm_mday, t.tm_hour,
                                                   t.tm_min, t.tm_sec, z)
    if style in ("rfc", "rfc2822"):
        return "%s, %d %s %d %02d:%02d:%02d %s" % (DAYS[t.tm_wday], t.tm_mday, MONTHS[t.tm_mon - 1],
                                                  t.tm_year, t.tm_hour, t.tm_min, t.tm_sec, tz_str)
    if style == "short":
        return "%04d-%02d-%02d" % (t.tm_year, t.tm_mon, t.tm_mday)
    if style == "raw":
        return "%d %s" % (ts, tz_str)
    if style == "unix":
        return str(ts)
    if style.startswith("format:"):
        return time.strftime(style[7:], t)
    return format_date(ts, tz)


def split_message(message):
    """(subject, body) like %s / %b: subject = first paragraph joined by spaces."""
    lines = message.split("\n")
    i = 0
    while i < len(lines) and not lines[i].strip():
        i += 1
    subj = []
    while i < len(lines) and lines[i].strip():
        subj.append(lines[i])
        i += 1
    while i < len(lines) and not lines[i].strip():
        i += 1
    body = "\n".join(lines[i:])
    return " ".join(s.rstrip() for s in subj), body


def _sanitize_subject(s):
    s = re.sub(r"[^A-Za-z0-9._]+", "-", s)
    s = re.sub(r"\.+", lambda m: ".", s)
    return s.strip("-.")


class Formatter:
    def __init__(self, repo, date_style="default", decorations=None, abbrev=None, abbrev_commit=False):
        self.repo = repo
        self.abbrev_commit = abbrev_commit
        self.date_style = date_style
        self.decorations = decorations or {}
        self.abbrev = abbrev

    def short(self, sha):
        return self.repo.odb.shorten(sha, self.abbrev)

    def decorate(self, sha, plain=False):
        names = self.decorations.get(sha)
        if not names:
            return ""
        return names if plain else " (" + names + ")"

    # ---- builtin layouts
    def hsha(self, sha):
        return self.short(sha) if self.abbrev_commit else sha

    def medium(self, sha, c, show_tagline=False):
        name, email, ts, tz = parse_ident(c.author)
        lines = ["commit %s%s" % (self.hsha(sha), self.decorate(sha))]
        if len(c.parents) > 1:
            lines.append("Merge: " + " ".join(self.short(p) for p in c.parents))
        lines.append("Author: %s <%s>" % (name, email))
        lines.append("Date:   " + format_date_style(ts, tz, self.date_style))
        lines.append("")
        return "\n".join(lines) + "\n" + self.indent_message(c.message)

    def indent_message(self, message):
        msg = message.rstrip("\n")
        if not msg:
            return ""
        return "".join("    " + ln + "\n" if ln else "    \n" for ln in msg.split("\n"))

    def short_fmt(self, sha, c):
        name, email, ts, tz = parse_ident(c.author)
        lines = ["commit %s%s" % (self.hsha(sha), self.decorate(sha))]
        if len(c.parents) > 1:
            lines.append("Merge: " + " ".join(self.short(p) for p in c.parents))
        lines.append("Author: %s <%s>" % (name, email))
        lines.append("")
        subj, _ = split_message(c.message)
        return "\n".join(lines) + "\n" + ("    " + subj + "\n" if subj else "")

    def full(self, sha, c, fuller=False):
        an, ae, ats, atz = parse_ident(c.author)
        cn, ce, cts, ctz = parse_ident(c.committer)
        lines = ["commit %s%s" % (self.hsha(sha), self.decorate(sha))]
        if len(c.parents) > 1:
            lines.append("Merge: " + " ".join(self.short(p) for p in c.parents))
        if fuller:
            lines.append("Author:     %s <%s>" % (an, ae))
            lines.append("AuthorDate: " + format_date_style(ats, atz, self.date_style))
            lines.append("Commit:     %s <%s>" % (cn, ce))
            lines.append("CommitDate: " + format_date_style(cts, ctz, self.date_style))
        else:
            lines.append("Author: %s <%s>" % (an, ae))
            lines.append("Commit: %s <%s>" % (cn, ce))
        lines.append("")
        return "\n".join(lines) + "\n" + self.indent_message(c.message)

    def oneline(self, sha, c):
        subj, _ = split_message(c.message)
        return "%s%s %s" % (self.short(sha), self.decorate(sha), subj)

    # ---- user format
    def expand(self, fmt, sha, c):
        an, ae, ats, atz = parse_ident(c.author)
        cn, ce, cts, ctz = parse_ident(c.committer)
        subj, body = split_message(c.message)
        out = []
        i, n = 0, len(fmt)
        ds = self.date_style
        while i < n:
            ch = fmt[i]
            if ch != "%" or i + 1 >= n:
                out.append(ch)
                i += 1
                continue
            nx = fmt[i + 1]
            two = fmt[i + 1:i + 3]
            if nx == "%":
                out.append("%")
                i += 2
            elif nx == "n":
                out.append("\n")
                i += 2
            elif nx == "H":
                out.append(sha)
                i += 2
            elif nx == "h":
                out.append(self.short(sha))
                i += 2
            elif nx == "T":
                out.append(c.tree)
                i += 2
            elif nx == "t":
                out.append(self.repo.odb.shorten(c.tree, self.abbrev))
                i += 2
            elif nx == "P":
                out.append(" ".join(c.parents))
                i += 2
            elif nx == "p":
                out.append(" ".join(self.short(p) for p in c.parents))
                i += 2
            elif nx == "s":
                out.append(subj)
                i += 2
            elif nx == "b":
                out.append(body + ("\n" if body and not body.endswith("\n") else ""))
                i += 2
            elif nx == "B":
                out.append(c.message)
                i += 2
            elif nx == "e":
                i += 2
            elif nx == "f":
                out.append(_sanitize_subject(subj))
                i += 2
            elif nx == "d":
                out.append(self.decorate(sha))
                i += 2
            elif nx == "D":
                out.append(self.decorate(sha, plain=True))
                i += 2
            elif nx == "x" and re.match(r"[0-9a-fA-F]{2}", fmt[i + 2:i + 4]):
                out.append(chr(int(fmt[i + 2:i + 4], 16)))
                i += 4
            elif nx in "ac" and two[1:2] in tuple("nNeEdDtrsiIDt") + ("",):
                who = (an, ae, ats, atz) if nx == "a" else (cn, ce, cts, ctz)
                k = two[1:2]
                if k in "nN":
                    out.append(who[0])
                elif k in "eE":
                    out.append(who[1])
                elif k == "d":
                    out.append(format_date_style(who[2], who[3], ds))
                elif k == "D":
                    out.append(format_date_style(who[2], who[3], "rfc"))
                elif k == "t":
                    out.append(str(who[2]))
                elif k == "i":
                    out.append(format_date_style(who[2], who[3], "iso"))
                elif k == "I":
                    out.append(format_date_style(who[2], who[3], "iso-strict"))
                elif k == "s":
                    out.append(format_date_style(who[2], who[3], "short"))
                else:
                    out.append("%" + two)
                    i += 3
                    continue
                i += 3
            elif nx == "C":
                m = re.match(r"%C(?:\([^)]*\)|red|green|blue|yellow|reset|bold|dim|ul|black|magenta|cyan|white)",
                             fmt[i:])
                if m:
                    i += m.end()
                else:
                    out.append("%")
                    i += 1
            else:
                out.append("%")
                i += 1
        return "".join(out)


def build_decorations(repo, head_sha=None):
    """{sha: 'HEAD -> master, tag: v1, other'} like %d (without parentheses)."""
    per = {}
    head = repo.head_sha()
    cur = repo.refs.head_branch()
    for name, sha in repo.refs.list("refs/"):
        if name.startswith("refs/heads/"):
            short = name[len("refs/heads/"):]
            per.setdefault(sha, []).append((1, short, name))
        elif name.startswith("refs/tags/"):
            short = name[len("refs/tags/"):]
            t, _ = repo.odb.read(sha)
            target = sha
            if t == "tag":
                try:
                    target = repo.peel(sha, "")
                except Exception:
                    pass
            per.setdefault(target, []).append((2, "tag: " + short, name))
        elif name.startswith("refs/remotes/"):
            per.setdefault(sha, []).append((3, name[len("refs/remotes/"):], name))
    res = {}
    all_shas = set(per)
    if head:
        all_shas.add(head)
    for sha in all_shas:
        items = []
        if sha == head:
            if cur is not None:
                items.append("HEAD -> " + cur)
            else:
                items.append("HEAD")
        rest = sorted(per.get(sha, []), key=lambda t: (t[0], t[1]))
        for kind, label, full in rest:
            if sha == head and cur is not None and full == "refs/heads/" + cur:
                continue
            items.append(label)
        res[sha] = ", ".join(items)
    return res
