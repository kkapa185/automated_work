from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from claude_session import detect_usage_limit, parse_cli_json
from process import ProcessResult
from usage_limits import UsageGate, compute_resume_at, parse_usage_limit

NOW = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)  # a Tuesday


@pytest.mark.parametrize("text,kind,expected", [
    ("Claude AI usage limit reached|1767225600", "unknown", datetime(2026, 1, 1, tzinfo=timezone.utc)),
    ("Claude AI usage limit reached|1767225600000", "unknown", datetime(2026, 1, 1, tzinfo=timezone.utc)),
    ("You've hit your session limit · resets 3pm (America/Los_Angeles)", "five_hour", datetime(2026, 11, 17, 23, 0, tzinfo=timezone.utc)),
    ("You've hit your session limit · resets 11am", "five_hour", datetime(2026, 11, 18, 11, 0, tzinfo=timezone.utc)),
    ("You've hit your session limit · resets 12:30pm (UTC)", "five_hour", datetime(2026, 11, 17, 12, 30, tzinfo=timezone.utc)),
    ("You've hit your weekly limit · resets Mon 9:30am (UTC)", "weekly", datetime(2026, 11, 23, 9, 30, tzinfo=timezone.utc)),
    ("You've hit your weekly limit · resets Tue 9am (UTC)", "weekly", datetime(2026, 11, 24, 9, 0, tzinfo=timezone.utc)),
    ("You've reached your Opus limit · resets Nov 18, 2pm", "weekly", datetime(2026, 11, 18, 14, 0, tzinfo=timezone.utc)),
    ("Weekly limit reached ∙ resets Jan 2, 2027, 8am (UTC)", "weekly", datetime(2027, 1, 2, 8, 0, tzinfo=timezone.utc)),
    ("5-hour limit reached ∙ resets in 2h 15m", "five_hour", NOW + timedelta(hours=2, minutes=15)),
    ("usage limit reached; resets at 2026-11-17T18:00:00Z", "unknown", datetime(2026, 11, 17, 18, tzinfo=timezone.utc)),
    ("You're out of usage credits", "unknown", None),
    ("Usage is paused for your organization", "unknown", None),
])
def test_parse_usage_limit(text, kind, expected):
    info = parse_usage_limit(text, NOW)
    assert info is not None and info.kind == kind and info.resets_at == expected


@pytest.mark.parametrize("text", [
    "API Error: 529 overloaded", "Error: context window limit exceeded", "Reached maximum turns",
    "Budget limit reached ($5)", "", "everything fine", "rate_limit_error: slow down",
])
def test_not_usage_limits(text):
    assert parse_usage_limit(text, NOW) is None


def test_detect_only_on_failed_invocations():
    ok = parse_cli_json('{"session_id": "s", "result": "I implemented the weekly limit feature; it resets at 3pm"}')
    proc = ProcessResult(argv=[], exit_code=0, stdout="", stderr="", duration_s=0)
    assert detect_usage_limit(proc, ok) is None
    err = parse_cli_json('{"session_id": "s", "is_error": true, "result": "You\'ve hit your session limit · resets 3pm"}')
    assert detect_usage_limit(proc, err).kind == "five_hour"
    raw = ProcessResult(argv=[], exit_code=1, stdout="Claude AI usage limit reached|1767225600", stderr="", duration_s=0)
    assert detect_usage_limit(raw, None) is not None


def test_compute_resume_at():
    info = parse_usage_limit("You've hit your session limit · resets 3pm (UTC)", NOW)
    assert compute_resume_at(info, NOW, 1, 120, [600]) == datetime(2026, 11, 17, 15, 2, tzinfo=timezone.utc)
    unknown = parse_usage_limit("You're out of usage credits", NOW)
    sched = [600, 1200, 2400]
    assert [compute_resume_at(unknown, NOW, n, 0, sched) - NOW for n in (1, 2, 3, 9)] == \
        [timedelta(seconds=s) for s in (600, 1200, 2400, 2400)]
    # A reset time already well in the past falls back to probing.
    stale = parse_usage_limit("usage limit reached|1700000000", NOW)
    assert compute_resume_at(stale, NOW, 1, 0, [600]) == NOW + timedelta(seconds=600)


class FakeClock:
    def __init__(self, start: datetime):
        self.t = start
        self.slept = 0.0

    def now(self) -> datetime:
        return self.t

    async def sleep(self, s: float) -> None:
        self.slept += s
        self.t += timedelta(seconds=s)


async def test_gate_waits_in_slices_and_opens():
    clk = FakeClock(NOW)
    g = UsageGate(clock=clk.now, sleep=clk.sleep, poll_s=60)
    assert not g.is_blocked and await g.wait() >= 0 and clk.slept == 0
    g.block(NOW + timedelta(minutes=5))
    g.block(NOW + timedelta(minutes=2))  # an earlier deadline never shortens the wait
    assert g.remaining_s() == 300
    await g.wait()
    assert clk.slept == pytest.approx(300) and not g.is_blocked and g.blocked_until is None
