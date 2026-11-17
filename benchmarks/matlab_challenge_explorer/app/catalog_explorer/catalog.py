"""Build the project catalog from a hub checkout."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from . import parser as P
from . import rules as R


class HubError(Exception):
    """Raised when the hub directory is unusable."""


def read_text(path: Path) -> str:
    return P.normalize_text(path.read_bytes().decode("utf-8", errors="replace"))


def load_trend_map(hub: Path) -> dict[str, list[str]]:
    """``{normalised project key: [megatrend names]}`` from ``megatrends/*.md``."""
    trends: dict[str, set[str]] = {}
    mdir = hub / "megatrends"
    if mdir.is_dir():
        for f in sorted(mdir.glob("*.md")):
            for folder in P.parse_megatrend_links(read_text(f)):
                trends.setdefault(P.norm_key(folder), set()).add(f.stem)
    return {k: sorted(v) for k, v in trends.items()}


def parse_project(readme: Path, hub: Path, trend_map: dict[str, list[str]]) -> dict | None:
    folder = readme.parent.name
    text = read_text(readme)
    sections = P.split_sections(text)
    pid = P.parse_project_number(text, sections)
    if not pid:
        print(f"warning: {readme}: no project number, skipped", file=sys.stderr)
        return None
    title = P.parse_title(text, folder)
    summary = P.parse_summary(text, sections)
    expertise = P.parse_expertise(sections)
    levels = P.parse_academic_levels(sections)
    impact = P.clean_inline(sections.get("impact", ""))
    trends = trend_map.get(P.norm_key(folder), []) or trend_map.get(P.norm_key(title), [])

    products = R.detect_products(text, sections)
    platforms = R.detect_platforms(text, products)
    tags = R.detect_hardware_tags(text)
    hw = R.classify_hardware_required(sections, text, tags)
    body = P.clean_inline(P.strip_urls("\n".join(
        v for k, v in sections.items() if k not in ("project number", "project discussion", "background material"))))
    ptypes = R.classify_project_types(title, summary, expertise, impact, body, products)
    areas = R.classify_application_areas(title, summary, expertise, impact, body, products, trends)
    difficulty = R.classify_difficulty(levels, sections.get("project difficulty", ""), text, hw, sections)
    partners = R.detect_partners(text, P.split_header_partner_text(text))

    return {
        "id": pid,
        "title": title,
        "project_url": P.project_url(folder),
        "source_file": readme.relative_to(hub).as_posix(),
        "summary": summary,
        "technology_trends": trends,
        "mathworks_platforms": platforms,
        "mathworks_products": [p for p in products],
        "expertise_gained_original": expertise,
        "difficulty": difficulty,
        "academic_levels": levels,
        "project_type": ptypes,
        "application_areas": areas,
        "hardware_required": hw,
        "hardware_tags": tags,
        "has_partner": bool(partners),
        "partners": partners,
        "partner_type": "industry" if partners else "",
        "thumbnail": P.parse_thumbnail(text),
    }


def _sort_key(p: dict):
    return (int(p["id"]) if p["id"].isdigit() else 10**9, p["title"].lower())


def build_catalog(hub: os.PathLike | str) -> list[dict]:
    hub = Path(hub)
    pdir = hub / "projects"
    if not pdir.is_dir():
        raise HubError(f"not a hub directory (missing projects/): {hub}")
    trend_map = load_trend_map(hub)
    projects: dict[str, dict] = {}
    for d in sorted(pdir.iterdir(), key=lambda x: x.name):
        readme = d / "README.md"
        if not (d.is_dir() and readme.is_file()):
            continue
        try:
            rec = parse_project(readme, hub, trend_map)
        except (OSError, ValueError) as e:  # unreadable / odd file: warn, keep going (R16)
            print(f"warning: {readme}: {e}, skipped", file=sys.stderr)
            continue
        if rec is None:
            continue
        if rec["id"] in projects:
            print(f"warning: duplicate project id {rec['id']} ({d.name}); later one wins", file=sys.stderr)
        projects[rec["id"]] = rec
    return sorted(projects.values(), key=_sort_key)


def write_catalog(projects: list[dict], out: os.PathLike | str) -> None:
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(projects, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
