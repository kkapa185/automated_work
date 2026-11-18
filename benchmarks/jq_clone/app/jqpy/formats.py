"""@format string implementations."""
import base64
import binascii
from .values import JQError, typename, tojson, fmt_number

UNRESERVED = set(b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_.~")


def tostring(v):
    return v if isinstance(v, str) else tojson(v)


def _trunc(v):
    from .interp import dump_trunc
    return dump_trunc(v)


def f_text(v):
    return tostring(v)


def f_json(v):
    return tojson(v)


def f_html(v):
    s = tostring(v)
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace("'", "&apos;").replace('"', "&quot;"))


def f_uri(v):
    out = []
    for b in tostring(v).encode("utf-8"):
        out.append(chr(b) if b in UNRESERVED else "%%%02X" % b)
    return "".join(out)


def f_urid(v):
    s = tostring(v)
    out = bytearray()
    i = 0
    b = s.encode("utf-8")
    n = len(b)
    while i < n:
        c = b[i]
        if c == 0x25:
            h = b[i + 1:i + 3]
            try:
                if len(h) != 2:
                    raise ValueError
                out.append(int(h, 16))
            except ValueError:
                raise JQError("%s (%s) is not a valid uri encoding" % (typename(v), _trunc(v)))
            i += 3
        else:
            out.append(c)
            i += 1
    return out.decode("utf-8", "replace")


def f_csv(v):
    if not isinstance(v, list):
        raise JQError("%s (%s) cannot be csv-formatted, only an array can be" % (typename(v), _trunc(v)))
    out = []
    for x in v:
        if x is None:
            out.append("")
        elif x is True:
            out.append("true")
        elif x is False:
            out.append("false")
        elif isinstance(x, (int, float)):
            out.append(fmt_number(x))
        elif isinstance(x, str):
            out.append('"' + x.replace('"', '""') + '"')
        else:
            raise JQError("%s (%s) is not valid in a csv row" % (typename(x), _trunc(x)))
    return ",".join(out)


def f_tsv(v):
    if not isinstance(v, list):
        raise JQError("%s (%s) cannot be tsv-formatted, only an array can be" % (typename(v), _trunc(v)))
    out = []
    for x in v:
        if x is None:
            out.append("")
        elif x is True:
            out.append("true")
        elif x is False:
            out.append("false")
        elif isinstance(x, (int, float)):
            out.append(fmt_number(x))
        elif isinstance(x, str):
            out.append(x.replace("\\", "\\\\").replace("\t", "\\t").replace("\n", "\\n").replace("\r", "\\r"))
        else:
            raise JQError("%s (%s) is not valid in a tsv row" % (typename(x), _trunc(x)))
    return "\t".join(out)


def _sh1(x):
    if isinstance(x, str):
        return "'" + x.replace("'", "'\\''") + "'"
    if isinstance(x, (list, dict)):
        raise JQError("%s (%s) can not be escaped for shell" % (typename(x), _trunc(x)))
    return tojson(x)


def f_sh(v):
    if isinstance(v, list):
        return " ".join(_sh1(x) for x in v)
    return _sh1(v)


def f_base64(v):
    return base64.b64encode(tostring(v).encode("utf-8")).decode("ascii")


def f_base64d(v):
    s = tostring(v)
    raw = s.encode("utf-8").rstrip(b"=")
    body = bytes(c for c in raw if c not in b"\r\n ")
    if len(body) % 4 == 1 and body:
        # a single dangling sextet carries no full byte; drop it like jq's decoder
        body = body[:-1]
    try:
        pad = b"=" * (-len(body) % 4)
        data = base64.b64decode(body + pad, validate=True)
    except (binascii.Error, ValueError):
        raise JQError("%s (%s) is not valid base64 data" % (typename(v), _trunc(v)))
    return data.decode("utf-8", "replace")


def f_base32(v):
    return base64.b32encode(tostring(v).encode("utf-8")).decode("ascii")


def f_base32d(v):
    s = tostring(v)
    raw = s.encode("utf-8").rstrip(b"=")
    try:
        data = base64.b32decode(raw + b"=" * (-len(raw) % 8))
    except (binascii.Error, ValueError):
        raise JQError("%s (%s) is not valid base32 data" % (typename(v), _trunc(v)))
    return data.decode("utf-8", "replace")


FORMATS = {
    "@text": f_text, "@json": f_json, "@html": f_html, "@uri": f_uri, "@urid": f_urid,
    "@csv": f_csv, "@tsv": f_tsv, "@sh": f_sh, "@base64": f_base64, "@base64d": f_base64d,
    "@base32": f_base32, "@base32d": f_base32d,
}


def get_format(name):
    from .lexer import JQSyntaxError
    if name not in FORMATS:
        raise JQSyntaxError("%s is not a valid format" % name[1:])
    return FORMATS[name]
