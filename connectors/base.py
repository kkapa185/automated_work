"""Shared connector primitives: the connector ABC and an HTTP retry helper."""

from __future__ import annotations

import asyncio
import logging
import random
from abc import ABC, abstractmethod
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

import httpx

from config import Settings
from schemas import ContextArtifact, ContextSource, SourceKind

log = logging.getLogger(__name__)

RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})

Sleeper = Callable[[float], Awaitable[None]]


class ConnectorError(Exception):
    """Raised by a connector when a source cannot be fetched."""


class BaseConnector(ABC):
    kind: SourceKind

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None, sleep: Sleeper | None = None):
        self.settings = settings
        self._client = client
        self._sleep = sleep or asyncio.sleep

    @abstractmethod
    async def fetch(self, source: ContextSource, workspace: str | None = None) -> ContextArtifact:
        """Fetch a source and return an artifact. May raise ConnectorError."""

    def enabled(self) -> bool:
        return True

    async def safe_fetch(self, source: ContextSource, workspace: str | None = None) -> ContextArtifact:
        """Never raises: failures are returned as an artifact with ``error`` set."""
        if not self.enabled():
            return ContextArtifact(kind=source.kind, ref=source.ref, error=f"{self.kind.value} connector is not configured")
        try:
            return await self.fetch(source, workspace)
        except Exception as exc:  # noqa: BLE001 - hydration must never crash the task
            log.warning("connector %s failed for %s: %s", self.kind.value, source.ref, exc)
            return ContextArtifact(kind=source.kind, ref=source.ref, error=f"{type(exc).__name__}: {exc}")

    async def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        if self._client is not None:
            return await request_with_retry(
                self._client, method, url, max_retries=self.settings.http_max_retries,
                base_delay=self.settings.backoff_base_s, max_delay=self.settings.backoff_max_s,
                sleep=self._sleep, **kwargs,
            )
        async with httpx.AsyncClient(timeout=self.settings.http_timeout_s, follow_redirects=True) as client:
            return await request_with_retry(
                client, method, url, max_retries=self.settings.http_max_retries,
                base_delay=self.settings.backoff_base_s, max_delay=self.settings.backoff_max_s,
                sleep=self._sleep, **kwargs,
            )


def backoff_delay(attempt: int, base: float, maximum: float) -> float:
    """Full-jitter exponential backoff: uniform(0, min(max, base * 2**attempt)), floored at base/2."""
    cap = min(maximum, base * (2 ** attempt))
    return max(base / 2, random.uniform(0, cap))


def _retry_after(resp: httpx.Response) -> float | None:
    value = resp.headers.get("Retry-After")
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        try:
            dt = parsedate_to_datetime(value)
            return max(0.0, (dt - datetime.now(timezone.utc)).total_seconds())
        except (TypeError, ValueError):
            return None


async def request_with_retry(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    sleep: Sleeper = asyncio.sleep,
    **kwargs: Any,
) -> httpx.Response:
    """Perform an HTTP request, retrying transport errors and 408/429/5xx responses."""
    attempt = 0
    while True:
        try:
            resp = await client.request(method, url, **kwargs)
        except (httpx.TransportError, httpx.TimeoutException) as exc:
            if attempt >= max_retries:
                raise ConnectorError(f"{method} {url} failed after {attempt + 1} attempts: {exc}") from exc
            delay = backoff_delay(attempt, base_delay, max_delay)
        else:
            if resp.status_code not in RETRYABLE_STATUS:
                if resp.status_code >= 400:
                    raise ConnectorError(f"{method} {url} -> HTTP {resp.status_code}: {resp.text[:300]}")
                return resp
            if attempt >= max_retries:
                raise ConnectorError(f"{method} {url} -> HTTP {resp.status_code} after {attempt + 1} attempts")
            delay = _retry_after(resp)
            if delay is None:
                delay = backoff_delay(attempt, base_delay, max_delay)
            delay = min(delay, max_delay)
        attempt += 1
        await sleep(delay)


def basic_or_bearer_auth(email: str | None, token: str | None) -> dict[str, Any]:
    """Atlassian Cloud uses email+API token basic auth; Server/DC uses a bearer PAT."""
    if not token:
        return {}
    if email:
        return {"auth": (email, token)}
    return {"headers": {"Authorization": f"Bearer {token}"}}
