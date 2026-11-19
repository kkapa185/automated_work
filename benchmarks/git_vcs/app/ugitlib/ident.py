"""Dates and author/committer identities."""
import calendar
import os
import re
import time
from email.utils import parsedate_tz

from .util import Fatal

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

_RAW_RE = re.compile(r"^@?(\d+)(?:\s+([+-])(\d{2})(\d{2}))?$")
_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2}))?(?:\.\d+)?\s*"
    r"(?:(Z)|([+-])(\d{2}):?(\d{2}))?$")


def local_tz_minutes(ts):
    return time.localtime(ts).tm_gmtoff // 60


def format_tz(minutes):
    sign = "-" if minutes < 0 else "+"
    m = abs(minutes)
    return "%s%02d%02d" % (sign, m // 60, m % 60)


def parse_tz(tz):
    """'+0530' -> minutes."""
    sign = -1 if tz[0] == "-" else 1
    return sign * (int(tz[1:3]) * 60 + int(tz[3:5]))


def parse_date(s):
    """Parse a date string; return (timestamp, tz_minutes). Raises ValueError."""
    s = s.strip()
    m = _RAW_RE.match(s)
    if m:
        ts = int(m.group(1))
        if m.group(2):
            tz = (1 if m.group(2) == "+" else -1) * (int(m.group(3)) * 60 + int(m.group(4)))
        else:
            tz = 0 if s.startswith("@") else local_tz_minutes(ts)
        return ts, tz
    m = _ISO_RE.match(s)
    if m:
        y, mo, d, h, mi = (int(m.group(i)) for i in range(1, 6))
        sec = int(m.group(6) or 0)
        if m.group(7):
            tz = 0
        elif m.group(8):
            tz = (1 if m.group(8) == "+" else -1) * (int(m.group(9)) * 60 + int(m.group(10)))
        else:
            tz = None
        local = calendar.timegm((y, mo, d, h, mi, sec))
        if tz is None:
            guess = local
            tz = local_tz_minutes(guess)
            tz = local_tz_minutes(local - tz * 60)
        return local - tz * 60, tz
    p = parsedate_tz(s)
    if p:
        tz = (p[9] or 0) // 60
        return calendar.timegm(p[:6]) - tz * 60, tz
    raise ValueError(s)


def format_date(ts, tz):
    """Default git date format: 'Tue Nov 14 22:13:20 2023 +0000'."""
    t = time.gmtime(ts + tz * 60)
    return "%s %s %d %02d:%02d:%02d %d %s" % (
        DAYS[t.tm_wday], MONTHS[t.tm_mon - 1], t.tm_mday, t.tm_hour, t.tm_min, t.tm_sec,
        t.tm_year, format_tz(tz))


_CRUD = " \t\n\r.,:;<>\"\\'"


def _clean(s):
    return s.strip(_CRUD).replace("<", "").replace(">", "").replace("\n", "")


def _identity_unknown(kind):
    import socket
    import getpass
    try:
        user = getpass.getuser()
    except Exception:
        user = "unknown"
    host = socket.gethostname()
    who = "Author" if kind == "AUTHOR" else "Committer"
    raise Fatal(
        "%s identity unknown\n\n*** Please tell me who you are.\n\nRun\n\n"
        "  git config --global user.email \"you@example.com\"\n"
        "  git config --global user.name \"Your Name\"\n\n"
        "to set your account's default identity.\n"
        "Omit --global to set the identity only in this repository.\n\n"
        "fatal: unable to auto-detect email address (got '%s@%s.(none)')" % (who, user, host),
        code=128, prefix="")


def get_ident(kind, config, env=None, strict=True):
    """Return 'Name <email> <ts> <tz>' for kind in ('AUTHOR', 'COMMITTER')."""
    env = os.environ if env is None else env
    name = env.get("GIT_%s_NAME" % kind)
    if name is None:
        name = config.get("user.name")
    email = env.get("GIT_%s_EMAIL" % kind)
    if email is None:
        email = config.get("user.email") or env.get("EMAIL")
    if name is None or email is None:
        if strict:
            _identity_unknown(kind)
        name, email = name or "unknown", email or "unknown@unknown"
    name_c, email_c = _clean(name), _clean(email)
    if not name_c:
        raise Fatal("empty ident name (for <%s>) not allowed" % email_c)
    date = env.get("GIT_%s_DATE" % kind)
    if date:
        try:
            ts, tz = parse_date(date)
        except ValueError:
            raise Fatal("invalid date format: %s" % date)
    else:
        ts = int(time.time())
        tz = local_tz_minutes(ts)
    return "%s <%s> %d %s" % (name_c, email_c, ts, format_tz(tz))
