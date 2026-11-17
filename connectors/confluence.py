"""Confluence REST connector: fetch a page and convert storage format to Markdown."""

from __future__ import annotations

import re

from connectors.base import BaseConnector, ConnectorError, basic_or_bearer_auth
from connectors.html import confluence_storage_to_markdown
from schemas import ContextArtifact, ContextSource, SourceKind

PAGE_ID_RES = (
    re.compile(r"/pages/(\d+)"),
    re.compile(r"[?&]pageId=(\d+)"),
    re.compile(r"^\s*(\d+)\s*$"),
)


def normalize_page_id(ref: str) -> str:
    for rx in PAGE_ID_RES:
        m = rx.search(ref)
        if m:
            return m.group(1)
    raise ConnectorError(f"not a Confluence page id or URL: {ref!r}")


class ConfluenceConnector(BaseConnector):
    kind = SourceKind.CONFLUENCE

    def enabled(self) -> bool:
        return self.settings.confluence_configured

    def _api_root(self) -> str:
        base = self.settings.confluence_base_url or ""
        # Cloud sites live under /wiki; Server/DC base URLs usually already point at the context root.
        if base.endswith("/wiki") or not base.endswith(".atlassian.net"):
            return base
        return base + "/wiki"

    async def fetch(self, source: ContextSource, workspace: str | None = None) -> ContextArtifact:
        s = self.settings
        page_id = normalize_page_id(source.ref)
        root = self._api_root()
        auth = basic_or_bearer_auth(s.confluence_email, s.confluence_api_token)
        headers = {"Accept": "application/json", **auth.pop("headers", {})}
        resp = await self.request(
            "GET",
            f"{root}/rest/api/content/{page_id}",
            params={"expand": "body.storage,version,space,ancestors"},
            headers=headers,
            **auth,
        )
        data = resp.json()
        title = data.get("title", f"Page {page_id}")
        storage = ((data.get("body") or {}).get("storage") or {}).get("value", "")
        markdown = confluence_storage_to_markdown(storage) if storage else ""
        space = (data.get("space") or {}).get("key")
        ancestors = [a.get("title", "") for a in data.get("ancestors") or []]
        header = [f"# {title}"]
        if space or ancestors:
            crumb = " / ".join([p for p in [space, *ancestors] if p])
            header.append(f"_Location: {crumb}_")
        content = "\n\n".join([*header, markdown or "_(empty page)_"])
        webui = ((data.get("_links") or {}).get("webui"))
        return ContextArtifact(
            kind=SourceKind.CONFLUENCE,
            ref=page_id,
            title=title,
            content=content,
            metadata={
                "space": space,
                "version": (data.get("version") or {}).get("number"),
                "url": f"{root}{webui}" if webui else None,
            },
        )
