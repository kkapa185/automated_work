"""Reference storage: loose refs, packed-refs, symbolic refs, HEAD."""
import os

from .util import Fatal, fsdecode, fsencode


def check_refname_format(name, allow_onelevel=False):
    """Return True when ``name`` is a valid ref name (git check-ref-format rules)."""
    if not name or name == "@":
        return False
    if name.startswith("/") or name.endswith("/") or name.endswith(".") or "//" in name:
        return False
    if "@{" in name or ".." in name:
        return False
    for ch in name:
        if ord(ch) < 0x20 or ord(ch) == 0x7F or ch in " ~^:?*[\\":
            return False
    parts = name.split("/")
    if len(parts) < 2 and not allow_onelevel:
        return False
    for p in parts:
        if p.startswith(".") or p.endswith(".lock") or p == "":
            return False
    return True


class RefStore:
    def __init__(self, gitdir):
        self.gitdir = gitdir
        self._packed = None
        self._packed_sig = None

    # ---- packed-refs
    def _packed_path(self):
        return os.path.join(self.gitdir, "packed-refs")

    def packed(self):
        """Return dict name -> sha from packed-refs (cached by stat signature)."""
        path = self._packed_path()
        try:
            st = os.stat(path)
            sig = (st.st_mtime_ns, st.st_size)
        except OSError:
            self._packed, self._packed_sig = {}, None
            return self._packed
        if self._packed is not None and sig == self._packed_sig:
            return self._packed
        refs = {}
        with open(path, "rb") as f:
            for line in f.read().splitlines():
                line = fsdecode(line)
                if not line or line[0] in "#^":
                    continue
                sha, _, name = line.partition(" ")
                if len(sha) == 40:
                    refs[name] = sha
        self._packed, self._packed_sig = refs, sig
        return refs

    def _write_packed(self, refs):
        path = self._packed_path()
        lines = ["# pack-refs with: peeled fully-peeled sorted "]
        for n in sorted(refs, key=fsencode):
            lines.append("%s %s" % (refs[n], n))
        tmp = path + ".lock"
        with open(tmp, "wb") as f:
            f.write(fsencode("\n".join(lines) + "\n"))
        os.replace(tmp, path)
        self._packed = None

    # ---- raw access
    def read_raw(self, name):
        """Return 'ref: target' / sha string, or None if the ref does not exist."""
        try:
            with open(os.path.join(self.gitdir, name), "rb") as f:
                return fsdecode(f.read()).strip()
        except (FileNotFoundError, NotADirectoryError, IsADirectoryError):
            pass
        sha = self.packed().get(name)
        return sha

    def symref_target(self, name):
        raw = self.read_raw(name)
        if raw and raw.startswith("ref:"):
            return raw[4:].strip()
        return None

    def resolve(self, name, depth=0):
        """Resolve a ref (following symbolic refs) to a sha, or None."""
        if depth > 10:
            raise Fatal("ref %s is a symbolic ref loop" % name)
        raw = self.read_raw(name)
        if raw is None:
            return None
        if raw.startswith("ref:"):
            return self.resolve(raw[4:].strip(), depth + 1)
        if len(raw) >= 40:
            return raw[:40]
        return None

    def final_ref(self, name):
        """Follow symbolic refs; return the name of the last ref in the chain."""
        for _ in range(10):
            t = self.symref_target(name)
            if t is None:
                return name
            name = t
        raise Fatal("ref %s is a symbolic ref loop" % name)

    def head_branch(self):
        """Current branch short name, or None when HEAD is detached."""
        t = self.symref_target("HEAD")
        if t and t.startswith("refs/heads/"):
            return t[len("refs/heads/"):]
        return None

    # ---- writing
    def _write_file(self, name, content):
        path = os.path.join(self.gitdir, name)
        d = os.path.dirname(path)
        try:
            os.makedirs(d, exist_ok=True)
        except (FileExistsError, NotADirectoryError):
            raise Fatal("cannot lock ref '%s': a parent path is not a directory" % name)
        if os.path.isdir(path):
            raise Fatal("cannot lock ref '%s': there is a directory in the way" % name)
        tmp = path + ".lock"
        try:
            with open(tmp, "wb") as f:
                f.write(fsencode(content))
            os.replace(tmp, path)
        except OSError as e:
            raise Fatal("cannot lock ref '%s': %s" % (name, e.strerror))

    def update(self, name, sha):
        """Point ``name`` to ``sha``; if it is a symbolic ref the target is updated."""
        name = self.final_ref(name)
        self._write_file(name, sha + "\n")

    def set_symbolic(self, name, target):
        self._write_file(name, "ref: %s\n" % target)

    def delete(self, name):
        path = os.path.join(self.gitdir, name)
        existed = False
        try:
            os.unlink(path)
            existed = True
        except OSError:
            pass
        packed = self.packed()
        if name in packed:
            refs = dict(packed)
            del refs[name]
            self._write_packed(refs)
            existed = True
        d = os.path.dirname(path)
        stop = os.path.join(self.gitdir, "refs")
        while existed and d.startswith(stop) and d != stop:
            try:
                os.rmdir(d)
            except OSError:
                break
            d = os.path.dirname(d)
        return existed

    # ---- listing
    def list(self, prefix="refs/"):
        """Sorted list of (name, sha) for all refs under ``prefix`` (loose + packed)."""
        refs = {n: s for n, s in self.packed().items() if n.startswith(prefix)}
        base = os.path.join(self.gitdir, prefix)
        top = prefix.rstrip("/")
        start = os.path.join(self.gitdir, top)
        if os.path.isdir(start):
            for root, dirs, files in os.walk(start):
                dirs.sort()
                for fn in files:
                    if fn.endswith(".lock"):
                        continue
                    rel = os.path.relpath(os.path.join(root, fn), self.gitdir)
                    if not (rel + ("/" if prefix.endswith("/") else "")).startswith(prefix):
                        continue
                    sha = self.resolve(rel)
                    if sha:
                        refs[rel] = sha
        elif os.path.isfile(start) and top.startswith(prefix.rstrip("/")):
            sha = self.resolve(top)
            if sha:
                refs[top] = sha
        del base
        return sorted(refs.items(), key=lambda kv: fsencode(kv[0]))


def _write_raw(self, name, content):
    """Write ``content`` to ref file ``name`` without following symbolic refs (e.g. detach HEAD)."""
    self._write_file(name, content)


RefStore.write_raw = _write_raw
