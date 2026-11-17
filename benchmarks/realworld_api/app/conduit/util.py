import re
from datetime import datetime, timezone

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def now_iso():
    """Current UTC time as ISO-8601 with milliseconds and a trailing Z."""
    d = datetime.now(timezone.utc)
    return d.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (d.microsecond // 1000)


RESERVED_SLUGS = {"feed"}  # would be shadowed by GET /articles/feed


def slugify(title):
    s = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return s or "article"


def unique_slug(db, title, exclude_id=None):
    base = slugify(title)
    slug, n = base, 1
    while True:
        row = db.execute("SELECT id FROM articles WHERE slug=?", (slug,)).fetchone()
        if slug not in RESERVED_SLUGS and (row is None or row["id"] == exclude_id):
            return slug
        n += 1
        slug = "%s-%d" % (base, n)


class ApiError(Exception):
    def __init__(self, status, errors):
        super().__init__(status)
        self.status = status
        self.errors = errors


def blank(v):
    return not isinstance(v, str) or not v.strip()
