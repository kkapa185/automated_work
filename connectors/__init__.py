"""Pluggable context ingestion connectors."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

import httpx

from config import Settings
from connectors.base import BaseConnector, ConnectorError, request_with_retry
from connectors.compiler import ContextCompiler
from connectors.confluence import ConfluenceConnector, normalize_page_id
from connectors.jira import ISSUE_KEY_RE, JiraConnector, normalize_issue_key
from connectors.local import GitDiffConnector, InlineTextConnector, LocalFileConnector, UrlConnector
from schemas import CompiledContext, ContextArtifact, ContextSource, SourceKind

__all__ = [
    "BaseConnector", "ConnectorError", "ContextCompiler", "ContextHydrator", "ConfluenceConnector",
    "GitDiffConnector", "InlineTextConnector", "JiraConnector", "LocalFileConnector", "UrlConnector",
    "detect_sources", "request_with_retry",
]

URL_RE = re.compile(r"https?://[^\s<>\"'`)\]]+")
JIRA_URL_RE = re.compile(r"/browse/([A-Z][A-Z0-9_]{1,9}-\d+)")
CONFLUENCE_URL_RE = re.compile(r"(/wiki/|/display/|/pages/\d+|pageId=\d+|confluence)", re.IGNORECASE)
GIT_DIFF_RE = re.compile(r"\bgit diff(?:\s+([\w./~^@-]+(?:\.\.\.?[\w./~^@-]+)?))?", re.IGNORECASE)
TRACE_FILE_RE = re.compile(r'File "([^"]+)", line \d+|\bat .*?\(([^():]+):\d+:\d+\)|^\s+at ([^\s():]+):\d+:\d+', re.MULTILINE)
PATH_RE = re.compile(r"(?<![\w/.:-])((?:~|\.{1,2})?/?(?:[\w.-]+/)*[\w.-]+\.[A-Za-z0-9]{1,8})(?![\w/])")
# Things that look like issue keys but are not.
NOT_ISSUE_PREFIXES = frozenset({"UTF", "ISO", "SHA", "RFC", "HTTP", "TLS", "SSL", "CVE", "MD", "PEP", "ES", "GPT", "X"})
MAX_DETECTED_FILES = 10


def detect_sources(text: str, workspace: str | None = None) -> list[ContextSource]:
    """Detect Jira keys/URLs, Confluence pages, git diffs, existing file paths and generic URLs."""
    found: dict[tuple[str, str], ContextSource] = {}

    def add(kind: SourceKind, ref: str) -> None:
        src = ContextSource(kind=kind, ref=ref)
        found.setdefault(src.key(), src)

    urls = URL_RE.findall(text)
    for url in urls:
        url = url.rstrip(".,;:")
        jm = JIRA_URL_RE.search(url)
        if jm:
            add(SourceKind.JIRA, jm.group(1))
        elif CONFLUENCE_URL_RE.search(url):
            try:
                add(SourceKind.CONFLUENCE, normalize_page_id(url))
            except ConnectorError:
                add(SourceKind.URL, url)
        else:
            add(SourceKind.URL, url)

    text_wo_urls = URL_RE.sub(" ", text)
    for key in ISSUE_KEY_RE.findall(text_wo_urls):
        if key.split("-")[0] not in NOT_ISSUE_PREFIXES:
            add(SourceKind.JIRA, key)

    for m in GIT_DIFF_RE.finditer(text_wo_urls):
        add(SourceKind.GIT_DIFF, m.group(1) or "working")

    candidates: list[str] = []
    for m in TRACE_FILE_RE.finditer(text):
        candidates.extend(g for g in m.groups() if g)
    candidates.extend(PATH_RE.findall(text_wo_urls))
    n = 0
    for cand in candidates:
        if n >= MAX_DETECTED_FILES:
            break
        p = Path(cand).expanduser()
        resolved = p if p.is_absolute() else (Path(workspace) / p if workspace else None)
        try:
            if resolved is not None and resolved.is_file():
                before = len(found)
                add(SourceKind.FILE, str(p) if not p.is_absolute() else str(resolved))
                n += len(found) - before
        except OSError:
            continue
    return list(found.values())


class ContextHydrator:
    """Runs every connector concurrently and compiles the result."""

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None, sleep=None):
        self.settings = settings
        file_c = LocalFileConnector(settings, client, sleep)
        text_c = InlineTextConnector(settings, client, sleep)
        self.connectors: dict[SourceKind, BaseConnector] = {
            SourceKind.JIRA: JiraConnector(settings, client, sleep),
            SourceKind.CONFLUENCE: ConfluenceConnector(settings, client, sleep),
            SourceKind.FILE: file_c,
            SourceKind.GIT_DIFF: GitDiffConnector(settings, client, sleep),
            SourceKind.URL: UrlConnector(settings, client, sleep),
            SourceKind.STACK_TRACE: text_c,
            SourceKind.TEXT: text_c,
        }
        self.compiler = ContextCompiler(settings.max_context_chars, settings.max_artifact_chars)

    def register(self, kind: SourceKind, connector: BaseConnector) -> None:
        self.connectors[kind] = connector

    def resolve_sources(self, description: str, explicit: list[ContextSource], auto_detect: bool, workspace: str | None) -> list[ContextSource]:
        sources: dict[tuple[str, str], ContextSource] = {}
        for s in explicit:
            if s.kind == SourceKind.JIRA:
                try:
                    s = ContextSource(kind=s.kind, ref=normalize_issue_key(s.ref))
                except ConnectorError:
                    pass
            sources.setdefault(s.key(), s)
        if auto_detect:
            for s in detect_sources(description, workspace):
                sources.setdefault(s.key(), s)
        return list(sources.values())

    async def fetch_all(self, sources: list[ContextSource], workspace: str | None) -> list[ContextArtifact]:
        async def one(src: ContextSource) -> ContextArtifact:
            conn = self.connectors.get(src.kind)
            if conn is None:
                return ContextArtifact(kind=src.kind, ref=src.ref, error=f"no connector for {src.kind.value}")
            return await conn.safe_fetch(src, workspace)

        return list(await asyncio.gather(*(one(s) for s in sources)))

    async def hydrate(
        self, description: str, explicit: list[ContextSource], auto_detect: bool = True, workspace: str | None = None
    ) -> CompiledContext:
        sources = self.resolve_sources(description, explicit, auto_detect, workspace)
        artifacts = await self.fetch_all(sources, workspace)
        return self.compiler.compile(description, artifacts)
