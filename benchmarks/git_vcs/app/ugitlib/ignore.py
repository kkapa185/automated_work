""".gitignore handling: pattern parsing, matching and per-directory lookup."""
import os
import re

from .util import fsdecode

_POSIX = {"alpha": "a-zA-Z", "digit": "0-9", "alnum": "a-zA-Z0-9", "upper": "A-Z", "lower": "a-z",
          "space": " \\t\\n\\r\\f\\v", "blank": " \\t", "punct": "!-/:-@\\[-`{-~", "xdigit": "0-9A-Fa-f",
          "word": "a-zA-Z0-9_", "cntrl": "\\x00-\\x1f\\x7f", "print": "\\x20-\\x7e", "graph": "\\x21-\\x7e"}


def glob_to_regex(pat, pathname=True):
    """Translate a gitignore/wildmatch glob into a regex string.

    ``*`` and ``?`` never match '/' (when ``pathname``); ``**`` handled per gitignore rules."""
    star = "[^/]*" if pathname else ".*"
    anyc = "[^/]" if pathname else "."
    i, n = 0, len(pat)
    res = []
    while i < n:
        c = pat[i]
        if c == "*":
            if pathname and pat.startswith("**", i):
                at_start = i == 0 or pat[i - 1] == "/"
                j = i
                while j < n and pat[j] == "*":
                    j += 1
                at_end = j == n
                if at_start and j < n and pat[j] == "/":
                    res.append("(?:.*/)?")
                    i = j + 1
                    continue
                if at_start and at_end:
                    res.append(".*")
                    i = j
                    continue
                if i > 0 and pat[i - 1] == "/" and at_end:
                    res.append(".*")
                    i = j
                    continue
                res.append(star)
                i = j
                continue
            res.append(star)
            i += 1
        elif c == "?":
            res.append(anyc)
            i += 1
        elif c == "[":
            j = i + 1
            if j < n and pat[j] in "!^":
                j += 1
            if j < n and pat[j] == "]":
                j += 1
            while j < n and pat[j] != "]":
                if pat[j] == "[" and j + 1 < n and pat[j + 1] == ":":
                    k = pat.find(":]", j + 2)
                    if k > 0:
                        j = k + 2
                        continue
                if pat[j] == "\\" and j + 1 < n:
                    j += 1
                j += 1
            if j >= n:
                res.append(re.escape(c))
                i += 1
                continue
            body = pat[i + 1:j]
            neg = body[:1] in ("!", "^")
            if neg:
                body = body[1:]
            out = []
            k = 0
            while k < len(body):
                ch = body[k]
                if ch == "[" and body.startswith("[:", k):
                    e = body.find(":]", k + 2)
                    if e > 0 and body[k + 2:e] in _POSIX:
                        out.append(_POSIX[body[k + 2:e]])
                        k = e + 2
                        continue
                if ch == "\\" and k + 1 < len(body):
                    k += 1
                    ch = body[k]
                if ch in "\\]^[":
                    out.append("\\" + ch)
                elif ch == "-" and 0 < k < len(body) - 1:
                    out.append("-")
                elif ch == "-":
                    out.append("\\-")
                else:
                    out.append(ch)
                k += 1
            cls = "".join(out)
            if pathname:
                res.append("(?:(?!/)[%s%s])" % ("^" if neg else "", cls))
            else:
                res.append("[%s%s]" % ("^" if neg else "", cls))
            i = j + 1
        elif c == "\\" and i + 1 < n:
            res.append(re.escape(pat[i + 1]))
            i += 2
        else:
            res.append(re.escape(c))
            i += 1
    return "".join(res)


class Pattern:
    __slots__ = ("negate", "dir_only", "has_slash", "regex", "text")

    def __init__(self, line):
        self.text = line
        self.negate = False
        if line.startswith("!"):
            self.negate = True
            line = line[1:]
        elif line.startswith("\\!") or line.startswith("\\#"):
            line = line[1:]
        self.dir_only = False
        if line.endswith("/"):
            self.dir_only = True
            line = line.rstrip("/")
        self.has_slash = "/" in line
        if line.startswith("/"):
            line = line[1:]
        self.regex = re.compile(glob_to_regex(line) + r"\Z", re.S)

    def matches(self, relpath, is_dir):
        if self.dir_only and not is_dir:
            return False
        if self.has_slash:
            return self.regex.match(relpath) is not None
        return self.regex.match(relpath.rsplit("/", 1)[-1]) is not None


def parse_patterns(text):
    pats = []
    for raw in text.split("\n"):
        line = raw.rstrip("\r")
        # strip trailing unescaped spaces
        while line.endswith(" ") and not line.endswith("\\ "):
            line = line[:-1]
        if not line or line.startswith("#"):
            continue
        line = re.sub(r"\\ ", " ", line) if line.endswith("\\ ") else line
        if line in ("!", "/"):
            continue
        pats.append(Pattern(line))
    return pats


def _load(path):
    try:
        with open(path, "rb") as f:
            return parse_patterns(fsdecode(f.read()))
    except (OSError, UnicodeError):
        return []


class IgnoreMatcher:
    """Answers "is this worktree-relative path ignored?" using .gitignore files, info/exclude and
    core.excludesFile.  Tracked-file exemption is the caller's responsibility."""

    def __init__(self, repo):
        self.repo = repo
        self._dir_pats = {}
        self._decided = {}
        self.extra = []
        env = repo.env
        self.extra.append(_load(os.path.join(repo.gitdir, "info", "exclude")))
        gf = repo.config.get("core.excludesfile")
        if gf:
            gf = os.path.expanduser(gf)
        else:
            xdg = env.get("XDG_CONFIG_HOME") or (os.path.join(env["HOME"], ".config")
                                                 if env.get("HOME") else None)
            gf = os.path.join(xdg, "git", "ignore") if xdg else None
        self.extra.append(_load(gf) if gf else [])

    def _patterns_for_dir(self, d):
        p = self._dir_pats.get(d)
        if p is None:
            wt = self.repo.worktree
            p = _load(os.path.join(wt, d, ".gitignore") if d else os.path.join(wt, ".gitignore"))
            self._dir_pats[d] = p
        return p

    @staticmethod
    def _decide(pats, rel, is_dir):
        for p in reversed(pats):
            if p.matches(rel, is_dir):
                return not p.negate
        return None

    def _check(self, path, is_dir):
        key = (path, is_dir)
        r = self._decided.get(key)
        if r is not None:
            return r
        parts = path.split("/")
        res = False
        decided = False
        for i in range(len(parts) - 1, -1, -1):
            d = "/".join(parts[:i])
            pats = self._patterns_for_dir(d)
            if pats:
                rel = path[len(d) + 1:] if d else path
                v = self._decide(pats, rel, is_dir)
                if v is not None:
                    res, decided = v, True
                    break
        if not decided:
            for pats in self.extra:
                v = self._decide(pats, path, is_dir)
                if v is not None:
                    res = v
                    break
        self._decided[key] = res
        return res

    def is_ignored(self, path, is_dir=False):
        parts = path.split("/")
        for i in range(1, len(parts)):
            if self._check("/".join(parts[:i]), True):
                return True
        return self._check(path, is_dir)
