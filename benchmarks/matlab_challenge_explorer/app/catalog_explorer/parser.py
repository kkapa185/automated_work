"""Low-level parsing of hub pages (README sections, header table, megatrend pages).

All functions are pure and tolerate missing / malformed input (R16).
"""
from __future__ import annotations

import html
import re
from urllib.parse import quote, unquote

REPO_TREE_URL = "https://github.com/mathworks/MATLAB-Simulink-Challenge-Project-Hub/tree/main/projects/"

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_H2_RE = re.compile(r"^##[ \t]+(.+?)[ \t#]*$", re.M)
_H1_HTML_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.S | re.I)
_IMG_RE = re.compile(r"<img\b[^>]*?\bsrc\s*=\s*[\"']([^\"']+)[\"']", re.I)
_URL_RE = re.compile(r"https?://[^\s)\"'<>]+")


def normalize_text(text: str) -> str:
    """Normalise newlines / BOM so all later regexes can assume ``\\n``."""
    return text.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")


def clean_inline(text: str) -> str:
    """Strip HTML tags and Markdown emphasis, unescape entities, collapse whitespace."""
    text = _TAG_RE.sub(" ", text)
    text = html.unescape(text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)  # md links -> text
    text = text.replace("**", "").replace("__", "")
    return _WS_RE.sub(" ", text).strip()


def strip_urls(text: str) -> str:
    return _URL_RE.sub(" ", text)


def split_sections(text: str) -> dict[str, str]:
    """Return ``{lower-cased heading: body}`` for level-2 headings (first one wins)."""
    text = normalize_text(text)
    matches = list(_H2_RE.finditer(text))
    sections: dict[str, str] = {}
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        key = _WS_RE.sub(" ", clean_inline(m.group(1))).lower()
        sections.setdefault(key, text[m.end():end].strip())
    return sections


def header_block(text: str) -> str:
    """The part of the page before the first ``## `` heading (form links + header table)."""
    text = normalize_text(text)
    m = _H2_RE.search(text)
    return text[: m.start()] if m else text


def parse_title(text: str, folder: str = "") -> str:
    text = normalize_text(text)
    m = _H1_HTML_RE.search(header_block(text)) or _H1_HTML_RE.search(text)
    if m:
        t = clean_inline(m.group(1))
        if t:
            return t
    m = re.search(r"^#[ \t]+(.+?)[ \t#]*$", text, re.M)
    if m and clean_inline(m.group(1)):
        return clean_inline(m.group(1))
    return folder


_SENT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])")


def first_sentence(text: str) -> str:
    text = _WS_RE.sub(" ", text).strip()
    if not text:
        return ""
    # do not split after common abbreviations such as "e.g." or "i.e."
    parts = _SENT_RE.split(text)
    out = parts[0]
    i = 1
    while re.search(r"\b(e\.g|i\.e|etc|vs|approx|Fig|No)\.$", out) and i < len(parts):
        out += " " + parts[i]
        i += 1
    return out


def parse_summary(text: str, sections: dict[str, str] | None = None) -> str:
    text = normalize_text(text)
    head = header_block(text)
    m = _H1_HTML_RE.search(head)
    if m:
        after = head[m.end():]
        for p in re.finditer(r"<p[^>]*>(.*?)</p>", after, re.S | re.I):
            s = clean_inline(p.group(1))
            if s:
                return first_sentence(s)
    sections = sections if sections is not None else split_sections(text)
    desc = sections.get("project description", "")
    for para in re.split(r"\n\s*\n", desc):
        s = clean_inline(para)
        if s and not s.lower().startswith(("suggested steps", "#")):
            return first_sentence(s)
    return ""


def parse_thumbnail(text: str) -> str:
    head = header_block(normalize_text(text))
    m = _IMG_RE.search(head)
    return html.unescape(m.group(1)).strip() if m else ""


def parse_project_number(text: str, sections: dict[str, str] | None = None) -> str:
    sections = sections if sections is not None else split_sections(text)
    body = sections.get("project number", "")
    m = re.search(r"\d+", clean_inline(body))
    if m:
        return m.group(0)
    m = re.search(r"tfa_2=(\d+)", normalize_text(text))
    return m.group(1) if m else ""


def split_items(text: str) -> list[str]:
    """Split a comma/semicolon/newline/bullet separated list into clean items."""
    text = clean_inline(text.replace("\n", ", ")) if text else ""
    items: list[str] = []
    seen: set[str] = set()
    for raw in re.split(r"[,;•]", text):
        item = raw.strip(" \t-*.")
        if not item:
            continue
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        items.append(item)
    return items


def parse_expertise(sections: dict[str, str]) -> list[str]:
    body = sections.get("expertise gained", "")
    # keep bullets on separate lines so that they split properly
    body = re.sub(r"^\s*[-*]\s+", "", body, flags=re.M)
    return split_items(body)


_LEVELS = [
    ("Bachelor", re.compile(r"bachelor", re.I)),
    ("Master's", re.compile(r"master", re.I)),
    ("Doctoral", re.compile(r"doctor|ph\.?d", re.I)),
]


def parse_academic_levels(sections: dict[str, str]) -> list[str]:
    body = clean_inline(sections.get("project difficulty", ""))
    return [name for name, rx in _LEVELS if rx.search(body)]


def project_url(folder: str) -> str:
    return REPO_TREE_URL + quote(folder)


def norm_key(name: str) -> str:
    """Normalised key used to match project names across pages."""
    s = unquote(name).lower().replace("modelling", "modeling")
    return re.sub(r"[^a-z0-9]+", "", s)


_HREF_RE = re.compile(r"href\s*=\s*[\"']([^\"']+)[\"']", re.I)
_MD_LINK_RE = re.compile(r"\]\(\s*<?((?:[^()\s<>]|\([^()\s]*\))+)>?[^)]*\)")


def parse_megatrend_links(text: str) -> list[str]:
    """Project folder names referenced by a megatrend page (URL-decoded, in order).

    Both HTML ``href`` attributes and Markdown links are understood; folder names may
    themselves contain parentheses (``Simulator%20(SAR)``).
    """
    text = normalize_text(text)
    targets = _HREF_RE.findall(text) + _MD_LINK_RE.findall(text)
    out: list[str] = []
    for url in targets:
        m = re.search(r"/projects/([^?#]+)", url) or re.match(r"projects/([^?#]+)", url)
        if not m:
            continue
        name = unquote(m.group(1)).split("/")[0].strip()
        if name and name not in out and not name.lower().endswith(".md"):
            out.append(name)
    return out


def split_header_partner_text(text: str) -> list[str]:
    """Names in sentences like ``developed in collaboration with **X**``."""
    names = []
    for m in re.finditer(r"in collaboration with\s+(?:\*\*|<strong>)(.+?)(?:\*\*|</strong>)", normalize_text(text), re.I):
        names.append(clean_inline(m.group(1)))
    return names
