"""Detect Claude subscription usage limits (5-hour session / weekly) and wait for their reset.

The CLI reports an exhausted allowance in several shapes, for example::

    Claude AI usage limit reached|1767225600
    You've hit your session limit · resets 3pm (America/Los_Angeles)
    You've hit your weekly limit · resets Mon 9:30am (UTC)
    You've reached your Opus limit · resets Nov 18, 2pm
    5-hour limit reached ∙ resets in 2h 15m

``parse_usage_limit`` turns such text into a ``UsageLimitInfo`` with the best reset
estimate it can find. ``UsageGate`` is a process-wide barrier: once any task hits the
limit, every task waits until the reset instead of burning calls on rejected requests.
"""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DETECT_RE = re.compile(
    r"usage limit reached|limit reached|hit your [\w\s-]*limit|reached your [\w\s-]*limit|"
    r"out of usage|usage (?:is )?paused|session limit|weekly limit|5-hour limit|five_hour|seven_day",
    re.IGNORECASE,
)
# Phrases that mention limits but are NOT subscription usage limits.
NOT_USAGE_RE = re.compile(r"context (?:window|length) limit|max(?:imum)? turns|budget limit reached|recursion limit", re.I)
EPOCH_RE = re.compile(r"\|\s*(\d{10})(?:\d{3})?\b")
RESETS_IN_RE = re.compile(
    r"resets?\s+in\s+(?:(\d+)\s*d(?:ays?)?)?\s*(?:(\d+)\s*h(?:ours?|rs?)?)?\s*(?:(\d+)\s*m(?:in(?:utes?)?)?)?", re.I
)
ISO_RE = re.compile(r"resets?(?:\s+at)?\s+(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2})?(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)", re.I)
CLOCK_RE = re.compile(
    r"resets?(?:\s+at)?\s+"
    r"(?:(?P<wday>mon|tue|wed|thu|fri|sat|sun)[a-z]*,?\s+)?"
    r"(?:(?P<mon>jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(?P<mday>\d{1,2})(?:st|nd|rd|th)?,?\s+"
    r"(?:(?P<year>\d{4}),?\s+)?(?:at\s+)?)?"
    r"(?P<hour>\d{1,2})(?::(?P<min>\d{2}))?\s*(?P<ampm>[ap]\.?m\.?)?"
    r"(?:\s*\((?P<tz>[A-Za-z_]+(?:/[A-Za-z_+-]+)*)\)|\s+(?P<tz2>UTC|GMT))?",
    re.I,
)
MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
WEEKDAYS = {d: i for i, d in enumerate(["mon", "tue", "wed", "thu", "fri", "sat", "sun"])}


@dataclass(frozen=True)
class UsageLimitInfo:
    kind: str  # "five_hour" | "weekly" | "unknown"
    resets_at: datetime | None
    message: str


def _kind(text: str) -> str:
    t = text.lower()
    if re.search(r"weekly|seven_day|7-day|\bweek\b|opus limit|sonnet limit|fable limit", t):
        return "weekly"
    if re.search(r"session limit|5-hour|five_hour|5h\b", t):
        return "five_hour"
    return "unknown"


def _tz(name: str | None, default: timezone | ZoneInfo) -> timezone | ZoneInfo:
    if not name:
        return default
    if name.upper() in ("UTC", "GMT", "Z"):
        return timezone.utc
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return default


def _parse_reset(text: str, now: datetime, local_tz: timezone | ZoneInfo) -> datetime | None:
    m = EPOCH_RE.search(text)
    if m:
        return datetime.fromtimestamp(int(m.group(1)), tz=timezone.utc)
    m = ISO_RE.search(text)
    if m:
        try:
            dt = datetime.fromisoformat(m.group(1).replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    m = RESETS_IN_RE.search(text)
    if m and any(m.groups()):
        d, h, mi = (int(x) if x else 0 for x in m.groups())
        return now + timedelta(days=d, hours=h, minutes=mi)
    m = CLOCK_RE.search(text)
    if m and (m.group("ampm") or m.group("min") or m.group("tz") or m.group("tz2")):
        tz = _tz(m.group("tz") or m.group("tz2"), local_tz)
        hour = int(m.group("hour"))
        minute = int(m.group("min") or 0)
        ampm = (m.group("ampm") or "").lower().replace(".", "")
        if ampm == "pm" and hour != 12:
            hour += 12
        elif ampm == "am" and hour == 12:
            hour = 0
        if hour > 23 or minute > 59:
            return None
        local_now = now.astimezone(tz)
        if m.group("mon"):
            year = int(m.group("year") or local_now.year)
            try:
                cand = datetime(year, MONTHS[m.group("mon")[:3].lower()], int(m.group("mday")), hour, minute, tzinfo=tz)
            except ValueError:
                return None
            if cand < local_now - timedelta(hours=1) and not m.group("year"):
                cand = cand.replace(year=year + 1)
            return cand.astimezone(timezone.utc)
        cand = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if m.group("wday"):
            delta = (WEEKDAYS[m.group("wday")[:3].lower()] - local_now.weekday()) % 7
            cand = cand + timedelta(days=delta)
            if cand <= local_now:
                cand += timedelta(days=7)
        elif cand <= local_now:
            cand += timedelta(days=1)
        return cand.astimezone(timezone.utc)
    return None


def parse_usage_limit(
    text: str, now: datetime | None = None, local_tz: timezone | ZoneInfo = timezone.utc
) -> UsageLimitInfo | None:
    """Return usage-limit details if ``text`` reports an exhausted subscription allowance."""
    if not text or not DETECT_RE.search(text) or NOT_USAGE_RE.search(text):
        return None
    now = now or datetime.now(timezone.utc)
    line = next((ln for ln in text.splitlines() if DETECT_RE.search(ln)), text)
    resets = _parse_reset(line, now, local_tz) or _parse_reset(text, now, local_tz)
    return UsageLimitInfo(kind=_kind(text), resets_at=resets, message=line.strip()[:500])


def compute_resume_at(
    info: UsageLimitInfo, now: datetime, consecutive: int, margin_s: float, probe_schedule_s: list[float]
) -> datetime:
    """When to try again: the parsed reset (+margin), else an escalating probe interval."""
    if info.resets_at is not None and info.resets_at > now - timedelta(minutes=5):
        return max(info.resets_at, now) + timedelta(seconds=margin_s)
    idx = min(max(consecutive - 1, 0), len(probe_schedule_s) - 1)
    return now + timedelta(seconds=probe_schedule_s[idx])


Clock = Callable[[], datetime]
Sleeper = Callable[[float], Awaitable[None]]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class UsageGate:
    """Process-wide barrier shared by all tasks while the account's usage allowance is exhausted."""

    def __init__(self, clock: Clock = utc_now, sleep: Sleeper = asyncio.sleep, poll_s: float = 60.0):
        self._clock = clock
        self._sleep = sleep
        self.poll_s = poll_s
        self.blocked_until: datetime | None = None
        self.info: UsageLimitInfo | None = None

    def block(self, until: datetime, info: UsageLimitInfo | None = None) -> None:
        if self.blocked_until is None or until > self.blocked_until:
            self.blocked_until = until
            self.info = info

    def remaining_s(self) -> float:
        if self.blocked_until is None:
            return 0.0
        return max(0.0, (self.blocked_until - self._clock()).total_seconds())

    @property
    def is_blocked(self) -> bool:
        return self.remaining_s() > 0

    async def wait(self) -> float:
        """Sleep until the gate opens. Sleeps in short slices so wall-clock jumps (suspend/resume) are honoured."""
        start = time.monotonic()
        while True:
            rem = self.remaining_s()
            if rem <= 0:
                break
            await self._sleep(min(rem, self.poll_s))
        if self.blocked_until is not None and self._clock() >= self.blocked_until:
            self.blocked_until = None
            self.info = None
        return time.monotonic() - start
