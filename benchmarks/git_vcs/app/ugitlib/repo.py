"""Repository discovery and revision resolution."""
import os
import re

from .config import Config
from .objects import (ObjectNotFound, ObjectStore, parse_commit, parse_tag, parse_tree)
from .refs import RefStore
from .util import Fatal

HEX_RE = re.compile(r"^[0-9a-fA-F]+$")


class BadRevision(Exception):
    def __init__(self, spec, ambiguous=False):
        super().__init__(spec)
        self.spec = spec
        self.ambiguous = ambiguous


def is_gitdir(path):
    return (os.path.isfile(os.path.join(path, "HEAD"))
            and os.path.isdir(os.path.join(path, "objects"))
            and os.path.isdir(os.path.join(path, "refs")))


def _read_gitfile(path):
    try:
        with open(path, "rb") as f:
            text = f.read().decode("utf-8", "surrogateescape").strip()
    except OSError:
        return None
    if text.startswith("gitdir:"):
        target = text[7:].strip()
        if not os.path.isabs(target):
            target = os.path.join(os.path.dirname(path), target)
        return os.path.normpath(target)
    return None


class Repo:
    def __init__(self, gitdir, worktree, cwd, env=None):
        self.gitdir = gitdir
        self.worktree = worktree
        self.env = os.environ if env is None else env
        self.prefix = ""
        if worktree:
            rel = os.path.relpath(cwd, worktree)
            if rel != "." and not rel.startswith(".."):
                self.prefix = rel.replace(os.sep, "/") + "/"
        objdir = self.env.get("GIT_OBJECT_DIRECTORY") or os.path.join(gitdir, "objects")
        self.odb = ObjectStore(objdir)
        self.refs = RefStore(gitdir)
        self._config = None
        self._commits = {}

    @property
    def config(self):
        if self._config is None:
            self._config = Config(self.gitdir, self.env)
        return self._config

    @property
    def bare(self):
        return self.worktree is None

    # ---- object helpers
    def read_object(self, sha):
        return self.odb.read(sha)

    def read_commit(self, sha):
        c = self._commits.get(sha)
        if c is None:
            t, data = self.odb.read(sha)
            if t != "commit":
                raise Fatal("%s is not a commit" % sha)
            c = self._commits[sha] = parse_commit(data)
        return c

    def read_tree(self, sha):
        t, data = self.odb.read(sha)
        if t != "tree":
            raise Fatal("%s is not a tree" % sha)
        return parse_tree(data)

    def update_ref(self, name, sha, msg):
        """Point ``name`` at ``sha`` and record reflog entries (branch log and, when HEAD
        points there, logs/HEAD)."""
        from . import reflog
        final = self.refs.final_ref(name)
        old = self.refs.resolve(final)
        self.refs.update(name, sha)
        reflog.append(self, final, old, sha, msg)
        if final != "HEAD" and self.refs.symref_target("HEAD") == final:
            reflog.append(self, "HEAD", old, sha, msg)
        elif name == "HEAD" and final == "HEAD":
            pass

    def log_head_move(self, old, new, msg):
        from . import reflog
        reflog.append(self, "HEAD", old, new, msg)

    def head_sha(self):
        return self.refs.resolve("HEAD")

    # ---- revision parsing
    def peel(self, sha, want):
        """Peel ``sha`` until it has type ``want`` ('' = fully peel tags)."""
        while True:
            t, data = self.odb.read(sha)
            if want and t == want:
                return sha
            if t == "tag":
                sha = parse_tag(data).object
                continue
            if not want:
                return sha
            if t == "commit" and want == "tree":
                return parse_commit(data).tree
            raise BadRevision("%s^{%s}" % (sha, want))

    def dwim_ref(self, name):
        """Resolve a short ref name to its full ref name using git's rules, or None."""
        cands = [name, "refs/" + name, "refs/tags/" + name, "refs/heads/" + name,
                 "refs/remotes/" + name, "refs/remotes/" + name + "/HEAD"]
        for c in cands:
            if c == name and not (name.startswith("refs/") or re.match(r"^[A-Z_]+$", name)):
                continue
            if self.refs.resolve(c):
                return c
        return None

    def _resolve_base(self, name):
        if len(name) == 40 and HEX_RE.match(name):
            return name.lower()
        full = self.dwim_ref(name)
        if full:
            return self.refs.resolve(full)
        if 4 <= len(name) < 40 and HEX_RE.match(name):
            m = self.odb.find_prefix(name.lower())
            if len(m) == 1:
                return m[0]
            if len(m) > 1:
                # prefer a unique commit among ambiguous candidates (git does the same
                # when a commit-ish is required); otherwise report ambiguity
                raise BadRevision(name, ambiguous=True)
        raise BadRevision(name)

    def resolve(self, spec, want_object=True):
        """Resolve a revision expression to a full hex sha (raises BadRevision)."""
        orig = spec
        if spec.startswith(":") and len(spec) > 1 and spec[1] != "/":
            return self._resolve_index_path(spec, orig)
        path = None
        # split at the first ':' that is not inside ^{...}
        depth = 0
        for i, ch in enumerate(spec):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
            elif ch == ":" and depth == 0:
                spec, path = spec[:i], spec[i + 1:]
                break
        sha = self._resolve_rev(spec, orig)
        if path is not None:
            return self._walk_path(sha, path, orig)
        return sha

    def _resolve_index_path(self, spec, orig):
        path = spec[1:]
        stage = 0
        m = re.match(r"^([0-3]):(.*)$", path)
        if m:
            stage, path = int(m.group(1)), m.group(2)
        try:
            from .index import Index
        except ImportError:
            raise BadRevision(orig)
        idx = Index.load(self)
        e = idx.get(path, stage)
        if e is None:
            raise BadRevision(orig)
        return e.sha

    def _walk_path(self, sha, path, orig):
        try:
            sha = self.peel(sha, "tree") if self.odb.read(sha)[0] != "tree" else sha
        except (BadRevision, ObjectNotFound):
            raise BadRevision(orig)
        if path.startswith("./"):
            path = self.prefix + path[2:]
        for part in [p for p in path.split("/") if p]:
            found = None
            if self.odb.read(sha)[0] != "tree":
                raise BadRevision(orig)
            for mode, name, esha in self.read_tree(sha):
                if name == part:
                    found = (mode, esha)
                    break
            if not found:
                raise BadRevision(orig)
            sha = found[1]
        return sha

    def _resolve_rev(self, spec, orig):
        m = re.match(r"^([^~^]*)(.*)$", spec, re.S)
        base, rest = m.group(1), m.group(2)
        if base == "@":
            base = "HEAD"
        if base == "":
            if not rest:
                raise BadRevision(orig)
            base = "HEAD"
        try:
            sha = self._resolve_base(base)
            if not self.odb.exists(sha):
                raise BadRevision(orig)
        except ObjectNotFound:
            raise BadRevision(orig)
        pos = 0
        while pos < len(rest):
            c = rest[pos]
            if rest.startswith("^{", pos):
                end = rest.find("}", pos)
                if end < 0:
                    raise BadRevision(orig)
                kind = rest[pos + 2:end]
                pos = end + 1
                if kind.startswith("/"):
                    raise BadRevision(orig)
                try:
                    if kind in ("", "tag"):
                        if kind == "tag":
                            if self.odb.read(sha)[0] != "tag":
                                raise BadRevision(orig)
                        else:
                            sha = self.peel(sha, "")
                    elif kind in ("commit", "tree", "blob"):
                        sha = self.peel(sha, kind)
                    elif kind == "object":
                        pass
                    else:
                        raise BadRevision(orig)
                except (BadRevision, ObjectNotFound):
                    raise BadRevision(orig)
                continue
            pos += 1
            mm = re.match(r"\d*", rest[pos:])
            num = mm.group(0)
            pos += len(num)
            try:
                commit_sha = self.peel(sha, "commit")
                if c == "~":
                    n = int(num) if num else 1
                    for _ in range(n):
                        parents = parse_commit(self.odb.read(commit_sha)[1]).parents
                        if not parents:
                            raise BadRevision(orig)
                        commit_sha = parents[0]
                    sha = commit_sha
                elif c == "^":
                    n = int(num) if num else 1
                    if n == 0:
                        sha = commit_sha
                    else:
                        parents = parse_commit(self.odb.read(commit_sha)[1]).parents
                        if n > len(parents):
                            raise BadRevision(orig)
                        sha = parents[n - 1]
                else:
                    raise BadRevision(orig)
            except (BadRevision, ObjectNotFound):
                raise BadRevision(orig)
        return sha

    def resolve_commit(self, spec):
        sha = self.resolve(spec)
        try:
            return self.peel(sha, "commit")
        except (BadRevision, ObjectNotFound):
            raise BadRevision(spec)


def discover(cwd, env=None):
    """Find the repository for ``cwd``; raises Fatal like git when there is none."""
    env = os.environ if env is None else env
    wt_env = env.get("GIT_WORK_TREE")
    gd_env = env.get("GIT_DIR")
    if gd_env:
        gd = os.path.abspath(gd_env)
        if not is_gitdir(gd):
            raise Fatal("not a git repository: '%s'" % gd_env)
        repo = Repo(gd, None, cwd, env)
        if wt_env:
            wt = os.path.abspath(wt_env)
        elif repo.config.get_bool("core.bare", False):
            wt = None
        else:
            wt = cwd
        return Repo(gd, wt, cwd, env)
    d = cwd
    while True:
        cand = os.path.join(d, ".git")
        if os.path.isdir(cand) and is_gitdir(cand):
            return Repo(cand, os.path.abspath(wt_env) if wt_env else d, cwd, env)
        if os.path.isfile(cand):
            target = _read_gitfile(cand)
            if target and is_gitdir(target):
                return Repo(target, os.path.abspath(wt_env) if wt_env else d, cwd, env)
        if is_gitdir(d) and not os.path.isdir(cand):
            r = Repo(d, None, cwd, env)
            return r
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    raise Fatal("not a git repository (or any of the parent directories): .git")
