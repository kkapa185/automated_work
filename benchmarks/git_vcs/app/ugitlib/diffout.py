"""Diff option parsing and output shared by diff, log and show."""
from . import diff as D
from .util import out, quote_path


class DiffOpts:
    def __init__(self):
        self.patch = None       # None = command default
        self.stat = False
        self.numstat = False
        self.shortstat = False
        self.name_only = False
        self.name_status = False
        self.summary = False
        self.ctx = 3
        self.renames = True
        self.quiet = False
        self.exit_code = False
        self.raw = False

    def any_format(self):
        return (self.stat or self.numstat or self.shortstat or self.name_only or self.name_status
                or self.summary or self.raw)

    def wants_patch(self, default):
        if self.patch is not None:
            return self.patch
        if self.any_format():
            return False
        return default


def parse_option(o, a):
    """Try to consume diff option ``a``; return True when recognised."""
    if a in ("-p", "-u", "--patch"):
        o.patch = True
    elif a in ("-s", "--no-patch"):
        o.patch = False
    elif a == "--stat" or a.startswith("--stat="):
        o.stat = True
    elif a == "--numstat":
        o.numstat = True
    elif a == "--shortstat":
        o.shortstat = True
    elif a == "--name-only":
        o.name_only = True
    elif a == "--name-status":
        o.name_status = True
    elif a == "--summary":
        o.summary = True
    elif a == "--raw":
        o.raw = True
    elif a == "--patch-with-stat":
        o.patch = True
        o.stat = True
    elif a in ("--no-renames",):
        o.renames = False
    elif a in ("-M", "--find-renames", "-C") or a.startswith("-M") or a.startswith("--find-renames="):
        o.renames = True
    elif a.startswith("-U") and a[2:].isdigit():
        o.ctx = int(a[2:])
    elif a.startswith("--unified="):
        o.ctx = int(a.split("=", 1)[1])
    elif a == "--exit-code":
        o.exit_code = True
    elif a in ("--quiet",):
        o.quiet = True
        o.exit_code = True
    elif a in ("--no-color", "--color=never", "--no-ext-diff", "--no-textconv", "--binary", "--full-index"):
        pass
    else:
        return False
    return True


def status_letter(p):
    return {"A": "A", "D": "D", "M": "M", "R": "R%03d" % (p.score * 100 // D.MAX_SCORE)}.get(
        p.status, p.status) if p.status != "M" else ("T" if (p.old.mode & 0o170000) != (p.new.mode & 0o170000) else "M")


def emit(repo, pairs, o, default_patch=True, sep=""):
    """Write the requested diff formats for ``pairs``. ``sep`` is printed before the first output."""
    if not pairs or o.quiet:
        return False
    wrote = False

    def w(text):
        nonlocal wrote
        if not wrote and sep:
            out(sep)
        wrote = True
        out(text)

    if o.name_only:
        for p in pairs:
            w(quote_path(p.path) + "\n")
    elif o.name_status:
        for p in pairs:
            if p.status == "R":
                w("%s\t%s\t%s\n" % (status_letter(p), quote_path(p.old_path), quote_path(p.new_path)))
            else:
                w("%s\t%s\n" % (status_letter(p), quote_path(p.path)))
    elif o.raw:
        z = "0" * 40
        for p in pairs:
            om = "%06o" % p.old.mode if p.old else "000000"
            nm = "%06o" % p.new.mode if p.new else "000000"
            osha = p.old.sha if p.old else z
            nsha = p.new.sha if p.new else z
            ab = lambda s: s[:7] if s != z else "0" * 7
            names = quote_path(p.old_path) + "\t" + quote_path(p.new_path) if p.status == "R" else quote_path(p.path)
            w(":%s %s %s... %s... %s\t%s\n" % (om, nm, ab(osha), ab(nsha), status_letter(p), names))
    if o.numstat:
        for p in pairs:
            ns = D.pair_numstat(p)
            name = D.pair_display_name(p) if p.status != "R" else "%s => %s" % (p.old_path, p.new_path)
            if ns is None:
                w("-\t-\t%s\n" % name)
            else:
                w("%d\t%d\t%s\n" % (ns[0], ns[1], name))
    if o.stat:
        w(D.format_stat_full(pairs))
    elif o.shortstat:
        _, files, ins, dele = D.format_stat(pairs)
        w(D.stat_summary_line(files, ins, dele))
    if o.summary:
        s = D.summary_lines(pairs)
        if s:
            w(s)
    if o.wants_patch(default_patch):
        if wrote and (o.stat or o.numstat or o.shortstat or o.summary):
            out("\n")
        w(D.format_patches(repo, pairs, o.ctx))
    return wrote
