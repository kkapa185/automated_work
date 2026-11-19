"""git-config file parsing, querying and editing."""
import os
import re

from .util import Fatal, fsdecode, fsencode

_KEY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9-]*$")


def parse_key(key):
    """'a.b.c' -> (section, subsection|None, name); raises ValueError(msg)."""
    if "." not in key:
        raise ValueError("key does not contain a section: %s" % key)
    section, rest = key.split(".", 1)
    if "." in rest:
        sub, name = rest.rsplit(".", 1)
    else:
        sub, name = None, rest
    if not section or not name:
        raise ValueError("key does not contain variable name: %s" % key)
    if not _KEY_RE.match(section) or not _KEY_RE.match(name):
        raise ValueError("invalid key: %s" % key)
    return section.lower(), sub, name.lower()


def canonical_key(sec, sub, name):
    return sec + ("." + sub if sub is not None else "") + "." + name


def parse_bool(value):
    if value is None:
        return True
    v = value.strip().lower()
    if v in ("true", "yes", "on", "1", ""):
        return v != ""
    if v in ("false", "no", "off", "0"):
        return False
    try:
        return int(v, 0) != 0
    except ValueError:
        raise Fatal("bad boolean config value '%s'" % value)


def parse_int(value):
    v = value.strip().lower()
    mult = 1
    if v and v[-1] in "kmg":
        mult = {"k": 1024, "m": 1024 ** 2, "g": 1024 ** 3}[v[-1]]
        v = v[:-1]
    try:
        return int(v, 0) * mult
    except ValueError:
        raise Fatal("bad numeric config value '%s'" % value)


def format_value(value):
    if value is None:
        return None
    need_quote = value != value.strip() or any(c in value for c in ";#")
    s = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\t", "\\t")
    return '"%s"' % s if need_quote else s


def format_header(sec, sub):
    if sub is None:
        return "[%s]" % sec
    return '[%s "%s"]' % (sec, sub.replace("\\", "\\\\").replace('"', '\\"'))


class Entry:
    __slots__ = ("sec", "sub", "name", "value", "start", "end", "hdr")

    def __init__(self, sec, sub, name, value, start, end, hdr):
        self.sec, self.sub, self.name, self.value = sec, sub, name, value
        self.start, self.end, self.hdr = start, end, hdr  # line indices [start, end]

    @property
    def key(self):
        return canonical_key(self.sec, self.sub, self.name)


class ConfigFile:
    """A single config file; supports reading, setting and unsetting keys."""

    def __init__(self, path):
        self.path = path
        self.lines = []
        self.entries = []
        self.headers = []  # (sec, sub, line_index)
        self.reload()

    def reload(self):
        self.lines, self.entries, self.headers = [], [], []
        try:
            with open(self.path, "rb") as f:
                text = fsdecode(f.read())
        except (FileNotFoundError, NotADirectoryError, IsADirectoryError):
            return
        self.lines = text.split("\n")
        if self.lines and self.lines[-1] == "":
            self.lines.pop()
        self._parse()

    def _parse(self):
        lines = self.lines
        i = 0
        sec = sub = None
        hdr_idx = -1
        n = len(lines)
        while i < n:
            line = lines[i]
            s = line.lstrip()
            if not s or s[0] in "#;":
                i += 1
                continue
            if s[0] == "[":
                m = re.match(r'\[\s*([A-Za-z0-9.-]+)\s*(?:"((?:[^"\\]|\\.)*)")?\s*\]', s)
                if not m:
                    raise Fatal("bad config line %d in file %s" % (i + 1, self.path))
                name = m.group(1)
                if m.group(2) is not None:
                    sec, sub = name.lower(), re.sub(r"\\(.)", r"\1", m.group(2))
                elif "." in name:
                    sec, sub = name.split(".", 1)
                    sec = sec.lower()
                    sub = sub.lower()
                else:
                    sec, sub = name.lower(), None
                hdr_idx = i
                self.headers.append((sec, sub, i))
                rest = s[m.end():].strip()
                if rest and rest[0] not in "#;":
                    # key on the same line as the header
                    lines[i] = lines[i][:len(line) - len(s) + m.end()]
                    lines.insert(i + 1, "\t" + rest)
                    n += 1
                i += 1
                continue
            if sec is None:
                raise Fatal("bad config line %d in file %s" % (i + 1, self.path))
            m = re.match(r"([A-Za-z][A-Za-z0-9-]*)", s)
            if not m:
                raise Fatal("bad config line %d in file %s" % (i + 1, self.path))
            name = m.group(1).lower()
            rest = s[m.end():].lstrip()
            start = i
            if not rest or rest[0] in "#;":
                self.entries.append(Entry(sec, sub, name, None, start, i, hdr_idx))
                i += 1
                continue
            if rest[0] != "=":
                raise Fatal("bad config line %d in file %s" % (i + 1, self.path))
            rest = rest[1:].lstrip()
            value = []
            inq = False
            cur = rest
            while True:
                j = 0
                cont = False
                while j < len(cur):
                    c = cur[j]
                    if c == "\\":
                        if j + 1 >= len(cur):
                            cont = True
                            j += 1
                            break
                        nx = cur[j + 1]
                        value.append({"n": "\n", "t": "\t", "b": "\b"}.get(nx, nx))
                        j += 2
                        continue
                    if c == '"':
                        inq = not inq
                    elif not inq and c in "#;":
                        break
                    else:
                        value.append(c)
                    j += 1
                if cont:
                    i += 1
                    if i >= n:
                        break
                    cur = lines[i]
                    continue
                break
            val = "".join(value)
            if not inq:
                # strip trailing whitespace that was not quoted: approximate by rstrip
                # unless the raw text ended with a quoted space.
                raw_tail = cur[:j].rstrip()
                if not raw_tail.endswith('"'):
                    val = val.rstrip()
            self.entries.append(Entry(sec, sub, name, val, start, i, hdr_idx))
            i += 1

    # ---- queries
    def items(self):
        return [(e.key, e.value) for e in self.entries]

    # ---- modification
    def _save(self):
        d = os.path.dirname(self.path)
        if d:
            os.makedirs(d, exist_ok=True)
        tmp = self.path + ".lock"
        with open(tmp, "wb") as f:
            f.write(fsencode("\n".join(self.lines) + ("\n" if self.lines else "")))
        os.replace(tmp, self.path)
        self.reload()

    def set(self, key, value, add=False, replace_all=False):
        sec, sub, name = parse_key(key)
        fv = format_value(value)
        newline = "\t%s = %s" % (name, fv)
        matches = [e for e in self.entries if (e.sec, e.sub, e.name) == (sec, sub, name)]
        if matches and not add:
            if len(matches) > 1 and not replace_all:
                raise Fatal("cannot overwrite multiple values with a single value\n"
                            "       Use a regexp, --add or --replace-all to change %s." % key,
                            code=5, prefix="warning: ")
            for e in reversed(matches if replace_all else matches[-1:]):
                self.lines[e.start:e.end + 1] = [newline] if e is matches[-1] else []
            self._save()
            return
        # insert after the last entry of the last matching section header
        hdrs = [h for h in self.headers if (h[0], h[1]) == (sec, sub)]
        if hdrs:
            hi = hdrs[-1][2]
            last = hi
            for e in self.entries:
                if e.hdr == hi:
                    last = max(last, e.end)
            self.lines.insert(last + 1, newline)
        else:
            self.lines.append(format_header(sec, sub))
            self.lines.append(newline)
        self._save()

    def unset(self, key, all_=False):
        sec, sub, name = parse_key(key)
        matches = [e for e in self.entries if (e.sec, e.sub, e.name) == (sec, sub, name)]
        if not matches:
            return False
        if len(matches) > 1 and not all_:
            raise Fatal("cannot unset '%s': multiple values" % key, code=5, prefix="warning: ")
        for e in reversed(matches):
            del self.lines[e.start:e.end + 1]
        # drop section headers left without any content
        self._save()
        self._drop_empty_sections()
        return True

    def _drop_empty_sections(self):
        changed = False
        hdr_lines = [h[2] for h in self.headers]
        for k, hi in reversed(list(enumerate(hdr_lines))):
            nxt = hdr_lines[k + 1] if k + 1 < len(hdr_lines) else len(self.lines)
            body = self.lines[hi + 1:nxt]
            if all(not b.strip() for b in body):
                del self.lines[hi:nxt]
                changed = True
        if changed:
            self._save()


class Config:
    """Layered configuration: system, global, local (later files override)."""

    def __init__(self, gitdir=None, env=None):
        env = os.environ if env is None else env
        self.env = env
        self.files = []
        self.local = None
        if not env.get("GIT_CONFIG_NOSYSTEM"):
            self.files.append(("system", ConfigFile(env.get("GIT_CONFIG_SYSTEM", "/etc/gitconfig"))))
        self.global_path = global_config_path(env)
        for p in global_config_paths(env):
            self.files.append(("global", ConfigFile(p)))
        if gitdir:
            self.local = ConfigFile(os.path.join(gitdir, "config"))
            self.files.append(("local", self.local))
        self.overrides = []

    def items(self):
        res = []
        for _, f in self.files:
            res.extend(f.items())
        res.extend(self.overrides)
        return res

    def get_all(self, key):
        try:
            sec, sub, name = parse_key(key)
        except ValueError:
            return []
        k = canonical_key(sec, sub, name)
        return [v for kk, v in self.items() if kk == k]

    def has(self, key):
        return bool(self.get_all(key))

    def get(self, key, default=None):
        vals = self.get_all(key)
        return vals[-1] if vals else default

    def get_bool(self, key, default=False):
        vals = self.get_all(key)
        if not vals:
            return default
        return parse_bool(vals[-1])

    def get_int(self, key, default=None):
        v = self.get(key)
        if v is None:
            return default
        return parse_int(v)


def global_config_paths(env):
    home = env.get("HOME")
    if "GIT_CONFIG_GLOBAL" in env:
        return [env["GIT_CONFIG_GLOBAL"]] if env["GIT_CONFIG_GLOBAL"] else []
    paths = []
    xdg = env.get("XDG_CONFIG_HOME") or (os.path.join(home, ".config") if home else None)
    if xdg:
        paths.append(os.path.join(xdg, "git", "config"))
    if home:
        paths.append(os.path.join(home, ".gitconfig"))
    return paths


def global_config_path(env):
    """The file that ``--global`` writes to."""
    if env.get("GIT_CONFIG_GLOBAL"):
        return env["GIT_CONFIG_GLOBAL"]
    home = env.get("HOME")
    return os.path.join(home, ".gitconfig") if home else None
