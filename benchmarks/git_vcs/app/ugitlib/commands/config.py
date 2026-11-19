"""git config"""
import os

from ..config import ConfigFile, canonical_key, format_value, parse_bool, parse_int, parse_key
from ..util import Fatal, out, err, usage_error, unknown_opt_msg

USAGE = "git config [<options>]"


def _fail(msg, code=1):
    raise Fatal("error: " + msg, code, prefix="")


def run(ctx, args):
    scope = None
    action = None
    vtype = None
    pos = []
    null = False
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("--local", "--global", "--system"):
            scope = a[2:]
        elif a in ("--get", "--get-all", "--add", "--unset", "--unset-all", "--list", "-l",
                   "--replace-all"):
            action = {"-l": "--list"}.get(a, a)
        elif a in ("--bool", "--int", "--bool-or-int", "--path"):
            vtype = a[2:]
        elif a == "-z":
            null = True
        elif a == "--default":
            i += 1
        elif a == "--":
            pos += args[i + 1:]
            break
        elif a.startswith("-") and len(a) > 1 and not a[1:].isdigit():
            usage_error(unknown_opt_msg(a), USAGE)
        else:
            pos.append(a)
        i += 1

    repo = ctx.try_repo()
    if action is None:
        if not pos:
            raise Fatal(USAGE, 129, prefix="usage: ")
        action = "--get" if len(pos) == 1 else "--set"
    env = ctx.env

    def files_for_read():
        from ..config import Config
        cfg = repo.config if repo else Config(None, env)
        if scope == "local":
            return [cfg.local] if cfg.local else []
        if scope == "global":
            return [f for s, f in cfg.files if s == "global"]
        return None

    def read_items():
        from ..config import Config
        sel = files_for_read()
        if sel is not None:
            res = []
            for f in sel:
                res.extend(f.items())
            return res
        cfg = repo.config if repo else Config(None, env)
        return cfg.items()

    def write_file():
        if scope == "global":
            from ..config import global_config_path
            p = global_config_path(env)
            if not p:
                raise Fatal("$HOME not set")
            return ConfigFile(p)
        if scope == "system":
            return ConfigFile(env.get("GIT_CONFIG_SYSTEM", "/etc/gitconfig"))
        if repo is None:
            raise Fatal("not in a git directory")
        return ConfigFile(os.path.join(repo.gitdir, "config"))

    def render(v):
        if vtype == "bool":
            return "true" if parse_bool(v) else "false"
        if vtype == "int":
            return str(parse_int(v)) if v is not None else "1"
        return v

    if action == "--list":
        for k, v in read_items():
            out(k + ("=" + v if v is not None else "") + ("\0" if null else "\n"))
        return 0

    key = pos[0]
    try:
        sec, sub, name = parse_key(key)
    except ValueError as e:
        _fail(str(e))
    ck = canonical_key(sec, sub, name)

    if action in ("--get", "--get-all"):
        vals = [v for k, v in read_items() if k == ck]
        if not vals:
            return 1
        for v in (vals if action == "--get-all" else vals[-1:]):
            r = render(v)
            out(("" if r is None else r) + "\n")
        return 0
    if action in ("--unset", "--unset-all"):
        cf = write_file()
        try:
            ok = cf.unset(key, all_=(action == "--unset-all"))
        except Fatal as e:
            err("%s%s\n" % (e.prefix, e.msg))
            return e.code
        return 0 if ok else 5
    # set / add / replace-all
    if len(pos) < 2:
        raise Fatal(USAGE, 129, prefix="usage: ")
    value = pos[1]
    if vtype == "bool":
        value = "true" if parse_bool(value) else "false"
    elif vtype == "int":
        value = str(parse_int(value))
    cf = write_file()
    try:
        cf.set(key, value, add=(action == "--add"), replace_all=(action == "--replace-all"))
    except Fatal as e:
        err("%s%s\n" % (e.prefix, e.msg))
        return e.code
    return 0
