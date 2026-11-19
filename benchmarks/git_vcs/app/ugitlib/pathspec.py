"""Pathspec parsing and matching (literal prefixes, wildcards, :(exclude), :/ magic)."""
import os
import re

from .ignore import glob_to_regex
from .util import Fatal

GLOB_CHARS = "*?[\\"


def normalize_path(repo, arg, top=False):
    """Convert a user path (relative to cwd or absolute) to a worktree-relative path."""
    wt = repo.worktree
    if os.path.isabs(arg):
        rel = os.path.relpath(os.path.normpath(arg), wt)
        if rel == ".." or rel.startswith("../"):
            raise Fatal("%s: '%s' is outside repository at '%s'" % (arg, arg, wt))
        rel = rel.replace(os.sep, "/")
        return "" if rel == "." else rel
    base = "" if top else repo.prefix
    parts = [p for p in base.split("/") if p]
    for comp in arg.split("/"):
        if comp in ("", "."):
            continue
        if comp == "..":
            if not parts:
                raise Fatal("%s: '%s' is outside repository at '%s'" % (arg, arg, wt))
            parts.pop()
        else:
            parts.append(comp)
    return "/".join(parts)


class Item:
    def __init__(self, orig, path, exclude, glob):
        self.orig = orig
        self.path = path
        self.exclude = exclude
        self.glob = glob
        self.regex = re.compile(glob_to_regex(path, pathname=False) + r"\Z", re.S) if glob else None

    def match(self, path):
        p = self.path
        if not self.glob:
            return p == "" or path == p or path.startswith(p + "/")
        # wildcard: the pattern may match the path or any of its leading directories
        if self.regex.match(path):
            return True
        i = path.find("/")
        while i >= 0:
            if self.regex.match(path[:i]):
                return True
            i = path.find("/", i + 1)
        return False

    def exact(self, path):
        if self.glob:
            return self.regex.match(path) is not None
        return self.path == path

    def may_contain(self, dirpath):
        """Could a path below directory ``dirpath`` match this item?"""
        if self.glob:
            return True
        p = self.path
        return p == "" or p == dirpath or p.startswith(dirpath + "/") or dirpath.startswith(p + "/")


class Pathspec:
    def __init__(self, repo, args, literal=False):
        self.items = []
        for a in args:
            exclude = False
            top = False
            glob_ok = not literal
            body = a
            if a.startswith(":") and not literal:
                if a.startswith(":("):
                    end = a.index(")") if ")" in a else -1
                    if end < 0:
                        raise Fatal("Missing ')' at the end of pathspec magic in '%s'" % a)
                    for w in a[2:end].split(","):
                        if w == "exclude":
                            exclude = True
                        elif w == "top":
                            top = True
                        elif w == "literal":
                            glob_ok = False
                    body = a[end + 1:]
                else:
                    j = 1
                    while j < len(a) and a[j] in "!^/":
                        if a[j] in "!^":
                            exclude = True
                        else:
                            top = True
                        j += 1
                    if j < len(a) and a[j] == ":":
                        j += 1
                    body = a[j:]
            path = normalize_path(repo, body, top)
            glob = glob_ok and any(c in path for c in GLOB_CHARS)
            self.items.append(Item(a, path, exclude, glob))
        self.includes = [i for i in self.items if not i.exclude]
        self.excludes = [i for i in self.items if i.exclude]

    def __bool__(self):
        return bool(self.items)

    def match(self, path):
        if self.includes:
            if not any(i.match(path) for i in self.includes):
                return False
        return not any(i.match(path) for i in self.excludes)

    def may_contain(self, dirpath):
        if self.includes and not any(i.may_contain(dirpath) for i in self.includes):
            return False
        return not any((not e.glob) and e.path != "" and (dirpath == e.path or dirpath.startswith(e.path + "/"))
                       for e in self.excludes)
