"""Date/time builtins (gmtime, mktime, strftime, strptime, ISO 8601 parsing)."""
import calendar
import math
import re
import time
from .values import JQError, typename, norm_num


def _isnum(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _dump(v):
    from .interp import dump_trunc
    return dump_trunc(v)


def _num(x):
    if isinstance(x, float) and x.is_integer() and abs(x) < 2 ** 53:
        return int(x)
    return x


def broken_down(secs, local=False):
    whole = math.floor(secs)
    frac = secs - whole
    try:
        t = time.localtime(whole) if local else time.gmtime(whole)
    except (OverflowError, OSError, ValueError):
        raise JQError("error converting number of seconds since epoch to datetime")
    sec = t.tm_sec + frac
    return [t.tm_year, t.tm_mon - 1, t.tm_mday, t.tm_hour, t.tm_min, _num(sec),
            (t.tm_wday + 1) % 7, t.tm_yday - 1]


def gmtime(v):
    if not _isnum(v):
        raise JQError("gmtime() requires a number")
    return broken_down(v)


def localtime(v):
    if not _isnum(v):
        raise JQError("localtime() requires a number")
    return broken_down(v, True)


def _check_bt(v, name):
    if not isinstance(v, list) or len(v) < 6 or not all(_isnum(x) for x in v):
        raise JQError("%s requires parsed datetime inputs" % name)
    return v


def mktime(v):
    if not isinstance(v, list):
        raise JQError("mktime requires array of 6 numbers")
    if len(v) < 6:
        raise JQError("mktime requires array of 6 numbers")
    if not all(_isnum(x) for x in v):
        raise JQError("mktime requires parsed datetime inputs")
    y, mo, d, h, mi, s = [math.floor(x) for x in v[:6]]
    days = calendar.timegm((y, 1, 1, 0, 0, 0)) // 86400
    # month may be out of range: normalise
    y += mo // 12
    mo = mo % 12
    secs = calendar.timegm((y, mo + 1, 1, 0, 0, 0)) + (d - 1) * 86400 + h * 3600 + mi * 60 + s
    return secs


def _struct(bt, local=False):
    y, mo, d, h, mi, s = [math.floor(x) for x in bt[:6]]
    wday = int(bt[6]) if len(bt) > 6 else 0
    yday = int(bt[7]) if len(bt) > 7 else 0
    return time.struct_time((y, mo + 1, d, h, mi, s, (wday + 6) % 7, yday + 1, 0))


def strftime(v, fmt, name="strftime/1", local=False):
    if _isnum(v):
        bt = broken_down(v, local)
    elif isinstance(v, list):
        bt = _check_bt(v, name)
    else:
        raise JQError("%s requires parsed datetime inputs" % name)
    if not isinstance(fmt, str):
        raise JQError("%s requires a string format" % name)
    if local:
        t0 = time.localtime(mktime(bt)) if _isnum(v) else None
        zone = time.strftime("%Z", t0) if t0 else time.strftime("%Z")
        off = time.strftime("%z", t0) if t0 else time.strftime("%z")
    else:
        zone, off = "UTC", "+0000"
    fmt = fmt.replace("%%", "\x00PCT\x00").replace("%Z", zone).replace("%z", off).replace("\x00PCT\x00", "%%")
    try:
        return time.strftime(fmt, _struct(bt))
    except ValueError:
        raise JQError("%s: unknown system failure" % name)


def strptime(v, fmt):
    if not isinstance(v, str) or not isinstance(fmt, str):
        raise JQError("strptime/1 requires string inputs and arguments")
    try:
        t = time.strptime(v, fmt)
    except ValueError:
        raise JQError('date "%s" does not match format "%s"' % (v, fmt))
    return [t.tm_year, t.tm_mon - 1, t.tm_mday, t.tm_hour, t.tm_min, t.tm_sec,
            (t.tm_wday + 1) % 7, t.tm_yday - 1]


# ---------------------------------------------------------------- ISO 8601
_DATE_RES = [
    ("cal", re.compile(r"(?P<y>[+-]\d{6}|\d{4})-(?P<m>\d\d)-(?P<d>\d\d)")),
    ("cal", re.compile(r"(?P<y>[+-]\d{6}|\d{4})(?P<m>\d\d)(?P<d>\d\d)")),
    ("ord", re.compile(r"(?P<y>[+-]\d{6}|\d{4})-(?P<j>\d{3})")),
    ("ord", re.compile(r"(?P<y>[+-]\d{6}|\d{4})(?P<j>\d{3})")),
    ("wk", re.compile(r"(?P<y>[+-]\d{6}|\d{4})-[Ww](?P<w>\d\d)-(?P<d>\d)")),
    ("wk", re.compile(r"(?P<y>[+-]\d{6}|\d{4})[Ww](?P<w>\d\d)(?P<d>\d)")),
]
_TIME_EXT = re.compile(r"(?P<h>\d\d)(?::(?P<mi>\d\d)(?::(?P<s>\d\d))?)?(?P<f>[.,]\d+)?$")
_TIME_BASIC = re.compile(r"(?P<h>\d\d)(?:(?P<mi>\d\d)(?P<s>\d\d)?)?(?P<f>[.,]\d+)?$")
_OFFSET = re.compile(r"(?:[Zz]|(?P<sg>[+-])(?P<oh>\d\d)(?::?(?P<om>\d\d))?)$")


def _days_from_civil(y, m, d):
    # days since 1970-01-01 for proleptic Gregorian date
    y -= m <= 2
    era = (y if y >= 0 else y - 399) // 400
    yoe = y - era * 400
    doy = (153 * (m + (-3 if m > 2 else 9)) + 2) // 5 + d - 1
    doe = yoe * 365 + yoe // 4 - yoe // 100 + doy
    return era * 146097 + doe - 719468


def _leap(y):
    return y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)


def _dim(y, m):
    return [31, 29 if _leap(y) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]


def _iso_week1_monday(y):
    # days-from-epoch of the Monday of ISO week 1 of year y
    jan4 = _days_from_civil(y, 1, 4)
    wd = (jan4 + 3) % 7   # Monday=0 (1970-01-01 is Thursday => +3)
    return jan4 - wd


def parse_iso8601(s):
    bad = JQError('date "%s" does not match format "%%Y-%%m-%%dT%%H:%%M:%%SZ"' % s)
    # split date part from the rest at 'T' / 't' / space
    m = re.match(r"^(.*?)(?:[Tt ](.*))?$", s, re.S)
    if s.count("T") + s.count("t") + s.count(" ") > 1:
        raise bad
    dpart, tpart = m.group(1), m.group(2)
    dm = None
    kind = None
    for k, rx in _DATE_RES:
        dm = rx.fullmatch(dpart)
        if dm:
            kind = k
            ext = "-" in dpart[4 if not dpart[0] in "+-" else 7:]
            break
    if not dm:
        raise bad
    ys = dm.group("y")
    y = int(ys)
    if ys[0] in "+-" and abs(y) < 10000 and False:
        raise bad
    if kind == "cal":
        mo, d = int(dm.group("m")), int(dm.group("d"))
        if not 1 <= mo <= 12 or not 1 <= d <= _dim(y, mo):
            raise bad
        days = _days_from_civil(y, mo, d)
    elif kind == "ord":
        j = int(dm.group("j"))
        if not 1 <= j <= (366 if _leap(y) else 365):
            raise bad
        days = _days_from_civil(y, 1, 1) + j - 1
    else:
        w, d = int(dm.group("w")), int(dm.group("d"))
        if not 1 <= d <= 7 or w < 1:
            raise bad
        weeks = 53 if (_iso_week1_monday(y + 1) - _iso_week1_monday(y)) // 7 == 53 else 52
        if w > weeks:
            raise bad
        days = _iso_week1_monday(y) + (w - 1) * 7 + d - 1
    secs = days * 86400
    frac = 0.0
    offset = 0
    if tpart is not None:
        # peel offset
        om = None
        for mm in re.finditer(r"[Zz]|[+-]\d\d(?::?\d\d)?", tpart):
            if mm.end() == len(tpart):
                om = mm
                break
        body = tpart
        if om:
            body = tpart[:om.start()]
            txt = om.group()
            if txt not in "Zz":
                sg = -1 if txt[0] == "-" else 1
                digits = txt[1:].replace(":", "")
                oh = int(digits[:2])
                omin = int(digits[2:4]) if len(digits) > 2 else 0
                if oh > 23 or omin > 59:
                    raise bad
                offset = sg * (oh * 3600 + omin * 60)
        if not body:
            raise bad
        extended = ":" in body
        date_ext = ("-" in dpart[1:]) if dpart[0] in "+-" else ("-" in dpart)
        hour_only = re.fullmatch(r"\d\d([.,]\d+)?", body) is not None
        if not hour_only and extended != date_ext:
            raise bad
        tm = (_TIME_EXT if extended else _TIME_BASIC).match(body)
        if not tm:
            raise bad
        h = int(tm.group("h"))
        mi = tm.group("mi")
        sec = tm.group("s")
        f = tm.groupdict().get("f")
        if f:
            fr = float("0." + f[1:])
        else:
            fr = 0.0
        if h > 24:
            raise bad
        mi_i = int(mi) if mi is not None else 0
        sec_i = int(sec) if sec is not None else 0
        if mi_i > 59 or sec_i > 60:
            raise bad
        if h == 24 and (mi_i or sec_i or fr):
            raise bad
        if sec_i == 60:
            if not (h == 23 and mi_i == 59):
                raise bad
            sec_i = 59
        secs += h * 3600 + mi_i * 60 + sec_i
        if f:
            # fraction belongs to the lowest component present
            if sec is not None:
                frac = fr
            elif mi is not None:
                frac = fr * 60
            else:
                frac = fr * 3600
    total = secs - offset
    if frac:
        return total + frac
    return total


def fromdateiso8601(v):
    if not isinstance(v, str):
        raise JQError("strptime/1 requires string inputs and arguments")
    r = parse_iso8601(v)
    return _num(r)


def todateiso8601(v):
    return strftime(v, "%Y-%m-%dT%H:%M:%SZ", "strftime/1")
