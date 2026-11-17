"""HTML / Confluence storage-format to Markdown conversion."""

from __future__ import annotations

import re

from markdownify import markdownify

_CODE_MACRO_RE = re.compile(
    r'<ac:structured-macro[^>]*ac:name="(?:code|noformat)"[^>]*>(.*?)</ac:structured-macro>',
    re.DOTALL | re.IGNORECASE,
)
_PANEL_MACRO_RE = re.compile(
    r'<ac:structured-macro[^>]*ac:name="(info|note|warning|tip|panel|expand)"[^>]*>(.*?)</ac:structured-macro>',
    re.DOTALL | re.IGNORECASE,
)
_LANG_RE = re.compile(r'<ac:parameter[^>]*ac:name="language"[^>]*>(.*?)</ac:parameter>', re.DOTALL | re.IGNORECASE)
_TITLE_RE = re.compile(r'<ac:parameter[^>]*ac:name="title"[^>]*>(.*?)</ac:parameter>', re.DOTALL | re.IGNORECASE)
_PLAIN_BODY_RE = re.compile(r"<ac:plain-text-body>\s*<!\[CDATA\[(.*?)\]\]>\s*</ac:plain-text-body>", re.DOTALL)
_RICH_BODY_RE = re.compile(r"<ac:rich-text-body>(.*?)</ac:rich-text-body>", re.DOTALL)
_AC_LINK_RE = re.compile(r"<ac:link[^>]*>(.*?)</ac:link>", re.DOTALL)
_RI_PAGE_RE = re.compile(r'<ri:page[^>]*ri:content-title="([^"]*)"[^>]*/?>')
_RI_URL_RE = re.compile(r'<ri:url[^>]*ri:value="([^"]*)"[^>]*/?>')
_LINK_BODY_RE = re.compile(r"<ac:(?:plain-text-)?link-body>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</ac:(?:plain-text-)?link-body>", re.DOTALL)
_TASK_RE = re.compile(
    r"<ac:task>.*?<ac:task-status>(.*?)</ac:task-status>.*?<ac:task-body>(.*?)</ac:task-body>.*?</ac:task>",
    re.DOTALL,
)
_REMAINING_AC_RE = re.compile(r"</?(?:ac|ri):[^>]*>")
_MULTI_NL_RE = re.compile(r"\n{3,}")
_DROP_BLOCKS_RE = re.compile(r"<(script|style|noscript|template)\b[^>]*>.*?</\1\s*>", re.DOTALL | re.IGNORECASE)
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _code_macro(m: re.Match[str]) -> str:
    inner = m.group(1)
    lang_m = _LANG_RE.search(inner)
    body_m = _PLAIN_BODY_RE.search(inner)
    lang = lang_m.group(1).strip() if lang_m else ""
    body = body_m.group(1) if body_m else ""
    cls = f' class="language-{lang}"' if lang else ""
    return f"<pre><code{cls}>{_escape(body)}</code></pre>"


def _panel_macro(m: re.Match[str]) -> str:
    name, inner = m.group(1).lower(), m.group(2)
    title_m = _TITLE_RE.search(inner)
    body_m = _RICH_BODY_RE.search(inner)
    body = body_m.group(1) if body_m else ""
    title = f"<strong>{name.upper()}{': ' + title_m.group(1) if title_m else ''}</strong>"
    return f"<blockquote><p>{title}</p>{body}</blockquote>"


def _ac_link(m: re.Match[str]) -> str:
    inner = m.group(1)
    body_m = _LINK_BODY_RE.search(inner)
    page_m = _RI_PAGE_RE.search(inner)
    url_m = _RI_URL_RE.search(inner)
    text = (body_m.group(1) if body_m else "") or (page_m.group(1) if page_m else "") or (url_m.group(1) if url_m else "")
    if url_m:
        return f'<a href="{url_m.group(1)}">{text}</a>'
    return text


def _task(m: re.Match[str]) -> str:
    done = m.group(1).strip() == "complete"
    return f"<p>[{'x' if done else ' '}] {m.group(2)}</p>"


def confluence_storage_to_markdown(storage: str) -> str:
    html = _CODE_MACRO_RE.sub(_code_macro, storage)
    # Panels can nest other macros; repeat until stable.
    for _ in range(5):
        new = _PANEL_MACRO_RE.sub(_panel_macro, html)
        if new == html:
            break
        html = new
    html = _AC_LINK_RE.sub(_ac_link, html)
    html = _TASK_RE.sub(_task, html)
    html = _REMAINING_AC_RE.sub("", html)
    return html_to_markdown(html)


def html_to_markdown(html: str) -> str:
    html = _COMMENT_RE.sub("", _DROP_BLOCKS_RE.sub("", html))
    md = markdownify(html, heading_style="ATX", bullets="-", code_language_callback=_lang_cb)
    return _MULTI_NL_RE.sub("\n\n", md).strip()


def _lang_cb(el) -> str | None:  # type: ignore[no-untyped-def]
    classes = el.get("class") or []
    if isinstance(classes, str):
        classes = classes.split()
    for c in classes:
        if c.startswith("language-"):
            return c[len("language-"):]
    code = el.find("code") if hasattr(el, "find") else None
    if code is not None and code is not el:
        return _lang_cb(code)
    return None
