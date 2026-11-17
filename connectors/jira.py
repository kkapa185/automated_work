"""Jira REST connector (Cloud v2/v3 and Server/DC v2)."""

from __future__ import annotations

import re
from typing import Any

from connectors.base import BaseConnector, ConnectorError, basic_or_bearer_auth
from connectors.html import html_to_markdown
from schemas import ContextArtifact, ContextSource, SourceKind

ISSUE_KEY_RE = re.compile(r"\b([A-Z][A-Z0-9_]{1,9}-\d{1,7})\b")
AC_HEADING_RE = re.compile(
    r"^\s*(?:h[1-6]\.\s*|#{1,6}\s*|\*+\s*)?(acceptance\s+criteria|definition\s+of\s+done)\s*:?\s*\**\s*$",
    re.IGNORECASE | re.MULTILINE,
)
NEXT_HEADING_RE = re.compile(r"^\s*(?:h[1-6]\.\s+|#{1,6}\s+)\S", re.MULTILINE)


def normalize_issue_key(ref: str) -> str:
    m = ISSUE_KEY_RE.search(ref)
    if not m:
        raise ConnectorError(f"not a Jira issue key or URL: {ref!r}")
    return m.group(1)


def adf_to_text(node: Any, _depth: int = 0) -> str:
    """Convert Atlassian Document Format (Jira v3) to Markdown-ish text."""
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "".join(adf_to_text(n, _depth) for n in node)
    if not isinstance(node, dict):
        return str(node)
    ntype = node.get("type")
    content = node.get("content", [])
    attrs = node.get("attrs", {}) or {}
    if ntype == "text":
        text = node.get("text", "")
        for mark in node.get("marks", []) or []:
            mt = mark.get("type")
            if mt == "code":
                text = f"`{text}`"
            elif mt == "strong":
                text = f"**{text}**"
            elif mt == "em":
                text = f"*{text}*"
            elif mt == "link":
                href = (mark.get("attrs") or {}).get("href")
                if href:
                    text = f"[{text}]({href})"
        return text
    if ntype == "hardBreak":
        return "\n"
    if ntype == "paragraph":
        return adf_to_text(content, _depth) + "\n\n"
    if ntype == "heading":
        level = int(attrs.get("level", 2))
        return "#" * level + " " + adf_to_text(content, _depth).strip() + "\n\n"
    if ntype in ("bulletList", "orderedList"):
        out = []
        for i, item in enumerate(content, 1):
            bullet = f"{i}." if ntype == "orderedList" else "-"
            body = adf_to_text(item.get("content", []), _depth + 1).strip()
            body = body.replace("\n\n", "\n").replace("\n", "\n" + "  " * (_depth + 1))
            out.append("  " * _depth + f"{bullet} {body}")
        return "\n".join(out) + "\n\n"
    if ntype == "listItem":
        return adf_to_text(content, _depth)
    if ntype == "codeBlock":
        lang = attrs.get("language", "") or ""
        return f"```{lang}\n{adf_to_text(content, _depth)}\n```\n\n"
    if ntype == "blockquote":
        inner = adf_to_text(content, _depth).strip()
        return "\n".join("> " + line for line in inner.splitlines()) + "\n\n"
    if ntype == "rule":
        return "---\n\n"
    if ntype in ("mention", "emoji"):
        return attrs.get("text") or attrs.get("shortName") or ""
    if ntype == "inlineCard":
        return attrs.get("url", "")
    return adf_to_text(content, _depth)


def extract_acceptance_criteria(description: str) -> str | None:
    m = AC_HEADING_RE.search(description)
    if not m:
        return None
    rest = description[m.end():]
    nxt = NEXT_HEADING_RE.search(rest)
    section = rest[: nxt.start()] if nxt else rest
    section = section.strip()
    return section or None


class JiraConnector(BaseConnector):
    kind = SourceKind.JIRA

    def enabled(self) -> bool:
        return self.settings.jira_configured

    def _field_text(self, value: Any, rendered: Any = None) -> str:
        if value is None:
            return ""
        if isinstance(value, dict) and value.get("type") == "doc":
            return adf_to_text(value).strip()
        if isinstance(value, str):
            return value.strip()
        if rendered and isinstance(rendered, str):
            return html_to_markdown(rendered)
        return str(value)

    async def fetch(self, source: ContextSource, workspace: str | None = None) -> ContextArtifact:
        s = self.settings
        key = normalize_issue_key(source.ref)
        url = f"{s.jira_base_url}/rest/api/{s.jira_api_version}/issue/{key}"
        auth = basic_or_bearer_auth(s.jira_email, s.jira_api_token)
        headers = {"Accept": "application/json", **auth.pop("headers", {})}
        resp = await self.request("GET", url, params={"expand": "renderedFields"}, headers=headers, **auth)
        data = resp.json()
        fields: dict[str, Any] = data.get("fields") or {}
        rendered: dict[str, Any] = data.get("renderedFields") or {}

        summary = fields.get("summary") or ""
        description = self._field_text(fields.get("description"), rendered.get("description"))
        ac = None
        if s.jira_acceptance_criteria_field:
            ac = self._field_text(fields.get(s.jira_acceptance_criteria_field)) or None
        if not ac:
            ac = extract_acceptance_criteria(description)

        lines = [f"# {key}: {summary}"]
        meta_bits = []
        for label, val in (
            ("Type", (fields.get("issuetype") or {}).get("name")),
            ("Status", (fields.get("status") or {}).get("name")),
            ("Priority", (fields.get("priority") or {}).get("name")),
            ("Assignee", (fields.get("assignee") or {}).get("displayName")),
        ):
            if val:
                meta_bits.append(f"- **{label}:** {val}")
        labels = fields.get("labels") or []
        if labels:
            meta_bits.append(f"- **Labels:** {', '.join(labels)}")
        if meta_bits:
            lines += ["", *meta_bits]
        lines += ["", "## Description", description or "_(empty)_"]
        if ac:
            lines += ["", "## Acceptance Criteria", ac]

        comments = ((fields.get("comment") or {}).get("comments")) or []
        comments = comments[-s.jira_max_comments:]
        if comments:
            lines += ["", "## Comments"]
            for c in comments:
                author = (c.get("author") or {}).get("displayName", "unknown")
                lines.append(f"- **{author}** ({c.get('created', '')}): {self._field_text(c.get('body'))}")

        linked: list[str] = []
        for link in fields.get("issuelinks") or []:
            ltype = link.get("type") or {}
            if "outwardIssue" in link:
                rel, other = ltype.get("outward", "relates to"), link["outwardIssue"]
            elif "inwardIssue" in link:
                rel, other = ltype.get("inward", "relates to"), link["inwardIssue"]
            else:
                continue
            ofields = other.get("fields") or {}
            linked.append(
                f"- {rel} **{other.get('key')}**: {ofields.get('summary', '')}"
                f" [{(ofields.get('status') or {}).get('name', '')}]"
            )
        for sub in fields.get("subtasks") or []:
            sf = sub.get("fields") or {}
            linked.append(f"- subtask **{sub.get('key')}**: {sf.get('summary', '')} [{(sf.get('status') or {}).get('name', '')}]")
        if linked:
            lines += ["", "## Linked Issues", *linked]

        return ContextArtifact(
            kind=SourceKind.JIRA,
            ref=key,
            title=f"{key}: {summary}",
            content="\n".join(lines).strip(),
            metadata={
                "url": f"{s.jira_base_url}/browse/{key}",
                "has_acceptance_criteria": bool(ac),
                "linked_issues": len(linked),
                "comments": len(comments),
            },
        )
