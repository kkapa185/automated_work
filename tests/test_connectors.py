from __future__ import annotations

import json
import subprocess
from pathlib import Path

import httpx
import pytest

from config import Settings
from connectors import ContextCompiler, ContextHydrator, detect_sources
from connectors.base import ConnectorError, request_with_retry
from connectors.confluence import ConfluenceConnector, normalize_page_id
from connectors.html import confluence_storage_to_markdown
from connectors.jira import JiraConnector, adf_to_text, extract_acceptance_criteria, normalize_issue_key
from connectors.local import GitDiffConnector, InlineTextConnector, LocalFileConnector, UrlConnector
from schemas import ContextArtifact, ContextSource, SourceKind


async def nosleep(_: float) -> None:
    return None


def jira_settings(**kw) -> Settings:
    return Settings(jira_base_url="https://acme.atlassian.net/", jira_email="bot@acme.test", jira_api_token="tok",
                    confluence_base_url="https://acme.atlassian.net", confluence_email="bot@acme.test",
                    confluence_api_token="tok", backoff_base_s=0.0, **kw)


def client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


JIRA_V2 = {
    "key": "PROJ-123",
    "fields": {
        "summary": "Login fails for SSO users",
        "description": "Users cannot log in.\n\nh3. Acceptance Criteria\n* SSO login works\n* Errors are logged\n\nh3. Notes\nnone",
        "issuetype": {"name": "Bug"}, "status": {"name": "To Do"}, "priority": {"name": "High"},
        "assignee": {"displayName": "Dev One"}, "labels": ["auth", "sso"],
        "comment": {"comments": [{"author": {"displayName": "QA"}, "created": "2026-01-01", "body": "Repro on staging"}]},
        "issuelinks": [
            {"type": {"inward": "is blocked by", "outward": "blocks"},
             "inwardIssue": {"key": "PROJ-100", "fields": {"summary": "IdP config", "status": {"name": "Done"}}}},
            {"type": {"inward": "is blocked by", "outward": "blocks"},
             "outwardIssue": {"key": "PROJ-200", "fields": {"summary": "Release", "status": {"name": "Open"}}}},
        ],
        "subtasks": [{"key": "PROJ-124", "fields": {"summary": "Add test", "status": {"name": "Open"}}}],
    },
}


async def test_jira_v2_fetch():
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["url"], seen["auth"] = str(req.url), req.headers.get("authorization")
        return httpx.Response(200, json=JIRA_V2)

    async with client(handler) as c:
        art = await JiraConnector(jira_settings(), c).fetch(ContextSource(kind=SourceKind.JIRA, ref="https://acme.atlassian.net/browse/PROJ-123"))
    assert seen["url"].startswith("https://acme.atlassian.net/rest/api/2/issue/PROJ-123?expand=renderedFields")
    assert seen["auth"].startswith("Basic ")
    assert art.title == "PROJ-123: Login fails for SSO users"
    for needle in ("## Acceptance Criteria", "SSO login works", "**Type:** Bug", "**QA**", "Repro on staging",
                   "is blocked by **PROJ-100**", "blocks **PROJ-200**", "subtask **PROJ-124**", "auth, sso"):
        assert needle in art.content, needle
    assert "none" not in art.content.split("## Acceptance Criteria")[1].split("## Comments")[0]
    assert art.metadata["has_acceptance_criteria"] and art.metadata["linked_issues"] == 3


async def test_jira_v3_adf_and_custom_ac_field_with_bearer():
    adf = {"type": "doc", "content": [
        {"type": "heading", "attrs": {"level": 2}, "content": [{"type": "text", "text": "Context"}]},
        {"type": "paragraph", "content": [{"type": "text", "text": "Run "}, {"type": "text", "text": "make", "marks": [{"type": "code"}]}]},
        {"type": "bulletList", "content": [{"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "item1"}]}]}]},
        {"type": "codeBlock", "attrs": {"language": "python"}, "content": [{"type": "text", "text": "print(1)"}]},
    ]}
    data = {"key": "AB-1", "fields": {"summary": "S", "description": adf,
                                      "customfield_100": {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Must be fast"}]}]}}}
    auth = {}

    def handler(req):
        auth["h"] = req.headers.get("authorization")
        assert "/rest/api/3/" in str(req.url)
        return httpx.Response(200, json=data)

    s = Settings(jira_base_url="https://jira.internal", jira_api_token="pat", jira_api_version="3",
                 jira_acceptance_criteria_field="customfield_100")
    async with client(handler) as c:
        art = await JiraConnector(s, c).fetch(ContextSource(kind=SourceKind.JIRA, ref="AB-1"))
    assert auth["h"] == "Bearer pat"
    assert "## Context" in art.content and "`make`" in art.content and "- item1" in art.content
    assert "```python\nprint(1)\n```" in art.content and "Must be fast" in art.content


async def test_jira_404_becomes_error_artifact():
    async with client(lambda r: httpx.Response(404, text="Issue does not exist")) as c:
        art = await JiraConnector(jira_settings(), c, nosleep).safe_fetch(ContextSource(kind=SourceKind.JIRA, ref="PROJ-9"))
    assert not art.ok and "404" in art.error


async def test_jira_not_configured():
    art = await JiraConnector(Settings()).safe_fetch(ContextSource(kind=SourceKind.JIRA, ref="PROJ-9"))
    assert art.error == "jira connector is not configured"


def test_issue_key_and_ac_helpers():
    assert normalize_issue_key("see https://x/browse/AB-12?focus=1") == "AB-12"
    with pytest.raises(ConnectorError):
        normalize_issue_key("nothing here")
    assert extract_acceptance_criteria("intro\n## Acceptance Criteria\n- a\n- b\n## Other\nx") == "- a\n- b"
    assert extract_acceptance_criteria("no criteria") is None
    assert adf_to_text({"type": "paragraph", "content": [{"type": "text", "text": "l", "marks": [{"type": "link", "attrs": {"href": "http://u"}}]}]}).strip() == "[l](http://u)"


async def test_request_retries_429_then_succeeds():
    calls = {"n": 0}
    delays = []

    def handler(req):
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(429 if calls["n"] == 1 else 503, headers={"Retry-After": "0.01"} if calls["n"] == 1 else {})
        return httpx.Response(200, json={"ok": True})

    async def rec(d):
        delays.append(d)

    async with client(handler) as c:
        resp = await request_with_retry(c, "GET", "https://x/y", max_retries=3, base_delay=0.01, sleep=rec)
    assert resp.json() == {"ok": True} and calls["n"] == 3 and delays[0] == pytest.approx(0.01)


async def test_request_retry_exhaustion_and_transport_error():
    async with client(lambda r: httpx.Response(500)) as c:
        with pytest.raises(ConnectorError, match="HTTP 500 after 3 attempts"):
            await request_with_retry(c, "GET", "https://x", max_retries=2, sleep=nosleep)

    def boom(r):
        raise httpx.ConnectError("refused")

    async with client(boom) as c:
        with pytest.raises(ConnectorError, match="failed after 2 attempts"):
            await request_with_retry(c, "GET", "https://x", max_retries=1, sleep=nosleep)


STORAGE = (
    '<h2>Overview</h2><p>Build the <strong>billing</strong> API. See <ac:link><ri:page ri:content-title="Data Model"/></ac:link>.</p>'
    '<ac:structured-macro ac:name="code"><ac:parameter ac:name="language">sql</ac:parameter>'
    '<ac:plain-text-body><![CDATA[SELECT * FROM t WHERE a < 5;]]></ac:plain-text-body></ac:structured-macro>'
    '<ac:structured-macro ac:name="warning"><ac:parameter ac:name="title">Careful</ac:parameter>'
    '<ac:rich-text-body><p>PCI scope</p></ac:rich-text-body></ac:structured-macro>'
    '<ac:task-list><ac:task><ac:task-id>1</ac:task-id><ac:task-status>complete</ac:task-status><ac:task-body>Design</ac:task-body></ac:task>'
    '<ac:task><ac:task-id>2</ac:task-id><ac:task-status>incomplete</ac:task-status><ac:task-body>Build</ac:task-body></ac:task></ac:task-list>'
    '<table><tr><th>Field</th><th>Type</th></tr><tr><td>id</td><td>uuid</td></tr></table>'
    '<ac:link><ri:url ri:value="https://ext.example/doc"/><ac:plain-text-link-body><![CDATA[ext doc]]></ac:plain-text-link-body></ac:link>'
)


def test_confluence_storage_to_markdown():
    md = confluence_storage_to_markdown(STORAGE)
    assert "## Overview" in md and "**billing**" in md and "See Data Model." in md
    assert "```sql\nSELECT * FROM t WHERE a < 5;\n```" in md
    assert "> **WARNING: Careful**" in md and "> PCI scope" in md
    assert "[x] Design" in md and "[ ] Build" in md
    assert "| Field | Type |" in md and "| id | uuid |" in md
    assert "[ext doc](https://ext.example/doc)" in md
    assert "ac:" not in md and "ri:" not in md


async def test_confluence_fetch():
    seen = {}

    def handler(req):
        seen["url"] = str(req.url)
        return httpx.Response(200, json={
            "id": "98765", "title": "Billing Spec", "space": {"key": "ENG"}, "version": {"number": 7},
            "ancestors": [{"title": "Specs"}], "body": {"storage": {"value": STORAGE}},
            "_links": {"webui": "/spaces/ENG/pages/98765"},
        })

    async with client(handler) as c:
        art = await ConfluenceConnector(jira_settings(), c).fetch(
            ContextSource(kind=SourceKind.CONFLUENCE, ref="https://acme.atlassian.net/wiki/spaces/ENG/pages/98765/Billing"))
    assert seen["url"].startswith("https://acme.atlassian.net/wiki/rest/api/content/98765?expand=body.storage")
    assert art.title == "Billing Spec" and "_Location: ENG / Specs_" in art.content and "```sql" in art.content
    assert art.metadata["version"] == 7


def test_page_id_normalization():
    assert normalize_page_id("12345") == "12345"
    assert normalize_page_id("https://c/pages/viewpage.action?pageId=777") == "777"
    with pytest.raises(ConnectorError):
        normalize_page_id("https://c/display/ENG/Home")


async def test_local_file_and_directory(tmp_path: Path):
    f = tmp_path / "app.py"
    f.write_text("print('hi')")
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "a.ts").write_text("export const a = 1")
    (tmp_path / "pkg" / "blob.bin").write_bytes(b"\x00\x01")
    (tmp_path / "pkg" / ".hidden").mkdir()
    (tmp_path / "pkg" / ".hidden" / "x.py").write_text("secret")
    conn = LocalFileConnector(Settings())
    art = await conn.fetch(ContextSource(kind=SourceKind.FILE, ref="app.py"), str(tmp_path))
    assert art.content == "```python\nprint('hi')\n```"
    d = await conn.fetch(ContextSource(kind=SourceKind.FILE, ref=str(tmp_path / "pkg")))
    assert "a.ts" in d.content and "blob.bin" not in d.content and "secret" not in d.content
    missing = await conn.safe_fetch(ContextSource(kind=SourceKind.FILE, ref="nope.py"), str(tmp_path))
    assert not missing.ok
    bin_art = await conn.safe_fetch(ContextSource(kind=SourceKind.FILE, ref=str(tmp_path / "pkg" / "blob.bin")))
    assert "binary" in bin_art.error


async def test_git_diff(tmp_path: Path):
    def git(*a):
        subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *a], cwd=tmp_path, check=True, capture_output=True)
    git("init", "-q")
    (tmp_path / "f.txt").write_text("one\n")
    git("add", ".")
    git("commit", "-qm", "init")
    (tmp_path / "f.txt").write_text("two\n")
    conn = GitDiffConnector(Settings())
    art = await conn.fetch(ContextSource(kind=SourceKind.GIT_DIFF, ref="working"), str(tmp_path))
    assert "-one" in art.content and "+two" in art.content
    bad = await conn.safe_fetch(ContextSource(kind=SourceKind.GIT_DIFF, ref="--output=/tmp/x"), str(tmp_path))
    assert "unsupported" in bad.error
    bad_rev = await conn.safe_fetch(ContextSource(kind=SourceKind.GIT_DIFF, ref="nosuchbranch...HEAD"), str(tmp_path))
    assert not bad_rev.ok


async def test_url_connector_html_json_and_binary():
    def handler(req):
        if req.url.path == "/doc":
            return httpx.Response(200, html="<h1>API</h1><script>x()</script><p>Use <code>GET /v1</code></p>")
        if req.url.path == "/j":
            return httpx.Response(200, json={"a": 1})
        return httpx.Response(200, content=b"\x89PNG", headers={"content-type": "image/png"})

    async with client(handler) as c:
        conn = UrlConnector(Settings(), c)
        doc = await conn.fetch(ContextSource(kind=SourceKind.URL, ref="https://docs.test/doc"))
        assert "# API" in doc.content and "`GET /v1`" in doc.content and "x()" not in doc.content
        j = await conn.fetch(ContextSource(kind=SourceKind.URL, ref="https://docs.test/j"))
        assert j.content.startswith("```json")
        img = await conn.safe_fetch(ContextSource(kind=SourceKind.URL, ref="https://docs.test/i.png"))
        assert "unsupported content type" in img.error
        ftp = await conn.safe_fetch(ContextSource(kind=SourceKind.URL, ref="ftp://x"))
        assert "scheme" in ftp.error


async def test_inline_text_connector():
    art = await InlineTextConnector(Settings()).fetch(ContextSource(kind=SourceKind.STACK_TRACE, ref="Traceback ...\nValueError"))
    assert art.title == "Stack trace" and "ValueError" in art.content


def test_detect_sources(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "api.py").write_text("x")
    text = (
        "Implement PROJ-123 and ABC-9 (not UTF-8 or SHA-256). Spec: https://acme.atlassian.net/wiki/spaces/E/pages/555/Spec. "
        "Ticket link https://acme.atlassian.net/browse/OPS-7, docs https://fastapi.tiangolo.com/tutorial/. "
        "Review git diff main...feature and fix src/api.py plus missing.py.\n"
        'Traceback (most recent call last):\n  File "src/api.py", line 3, in <module>\n'
    )
    got = {(s.kind, s.ref) for s in detect_sources(text, str(tmp_path))}
    assert got == {
        (SourceKind.JIRA, "PROJ-123"), (SourceKind.JIRA, "ABC-9"), (SourceKind.JIRA, "OPS-7"),
        (SourceKind.CONFLUENCE, "555"), (SourceKind.URL, "https://fastapi.tiangolo.com/tutorial/"),
        (SourceKind.GIT_DIFF, "main...feature"), (SourceKind.FILE, "src/api.py"),
    }


def test_detect_plain_git_diff_and_nothing():
    assert [(s.kind, s.ref) for s in detect_sources("look at the git diff")] == [(SourceKind.GIT_DIFF, "working")]
    assert detect_sources("just build a todo app") == []


def test_compiler_structure_and_truncation():
    arts = [
        ContextArtifact(kind=SourceKind.JIRA, ref="P-1", title='a "q"', content="A" * 500),
        ContextArtifact(kind=SourceKind.URL, ref="u", title="u", content="B" * 5000),
        ContextArtifact(kind=SourceKind.JIRA, ref="P-2", error="boom"),
    ]
    out = ContextCompiler(max_total_chars=100_000, max_artifact_chars=1000).compile("do it", arts)
    assert out.payload.startswith("<task_request>\ndo it\n</task_request>")
    assert '<artifact kind="jira" ref="P-1" title=\'a "q"\'>' in out.payload
    assert "characters truncated" in out.payload and out.truncated
    assert "- jira P-2: boom" in out.payload and out.payload.endswith("</context>")
    tight = ContextCompiler(max_total_chars=800, max_artifact_chars=1000).compile("do it", arts)
    assert 'omitted="budget"' in tight.payload and len(tight.payload) < 1500


async def test_hydrator_dedupes_and_survives_failures(tmp_path: Path):
    (tmp_path / "notes.md").write_text("remember X")

    def handler(req):
        return httpx.Response(200, json=JIRA_V2) if "/issue/" in str(req.url) else httpx.Response(500)

    async with client(handler) as c:
        h = ContextHydrator(jira_settings(http_max_retries=0), c, nosleep)
        ctx = await h.hydrate(
            "Fix PROJ-123, see notes.md and https://broken.test/x",
            [ContextSource(kind=SourceKind.JIRA, ref="https://acme.atlassian.net/browse/PROJ-123")],
            workspace=str(tmp_path),
        )
    kinds = sorted((a.kind.value, a.ok) for a in ctx.artifacts)
    assert kinds == [("file", True), ("jira", True), ("url", False)]
    assert "remember X" in ctx.payload and "Login fails for SSO users" in ctx.payload
    assert ctx.payload.count('ref="PROJ-123"') == 1


async def test_hydrator_without_autodetect(tmp_path: Path):
    ctx = await ContextHydrator(Settings()).hydrate("Fix PROJ-1", [], auto_detect=False)
    assert ctx.artifacts == [] and "<context>\n</context>" in ctx.payload
