from pathlib import Path

from catalog_explorer import parser as P
from catalog_explorer.catalog import build_catalog, parse_project, load_trend_map
from tests.conftest import SYNTH_PAGE


def synth_record(tmp_path):
    d = tmp_path / "projects" / "Some Folder"
    d.mkdir(parents=True)
    f = d / "README.md"
    f.write_text(SYNTH_PAGE, encoding="utf-8")
    return parse_project(f, tmp_path, {})


def test_r2_r3_r5_r6_synthetic_page_crlf(tmp_path):
    rec = synth_record(tmp_path)
    assert rec["id"] == "777"
    assert rec["title"] == "Synthetic & Test Project"
    assert rec["summary"] == "Build a thing with MATLAB."
    assert rec["thumbnail"] == "https://example.com/pic.png"
    assert rec["source_file"] == "projects/Some Folder/README.md"
    assert rec["project_url"].endswith("/tree/main/projects/Some%20Folder")


def test_r8_expertise_normalised():
    secs = P.split_sections("## Expertise Gained \n\nA,  B ,a;\n- C\n\n## X\n")
    assert P.parse_expertise(secs) == ["A", "B", "C"]


def test_r9_levels_variants():
    for text, expect in [
        ("Master’s level", ["Master's"]),
        ("Doctoral, Bachelor, Master's", ["Bachelor", "Master's", "Doctoral"]),
        ("Master's, Doctoral level", ["Master's", "Doctoral"]),
        ("", []),
    ]:
        assert P.parse_academic_levels({"project difficulty": text}) == expect


def test_r2_number_fallback_and_missing():
    assert P.parse_project_number("x ...tfa_2=42 y") == "42"
    assert P.parse_project_number("## Project Number\n\n  12 \n") == "12"
    assert P.parse_project_number("nothing") == ""


def test_r3_title_fallbacks():
    assert P.parse_title("# Plain Heading\n", "folder") == "Plain Heading"
    assert P.parse_title("no heading", "folder") == "folder"
    assert P.parse_title("<h1> A\n B </h1>") == "A B"


def test_r5_summary_fallback_description():
    text = "## Project Description\n\nDo the thing e.g. quickly. Then more.\n"
    assert P.parse_summary(text) == "Do the thing e.g. quickly."


def test_r16_empty_and_bom_page(tmp_path):
    d = tmp_path / "projects" / "P"
    d.mkdir(parents=True)
    (d / "README.md").write_text("﻿", encoding="utf-8")
    assert parse_project(d / "README.md", tmp_path, {}) is None


def test_r7_megatrend_links_with_parentheses_and_markdown():
    text = ('<a href="https://x/blob/main/projects/Synthetic%20Aperture%20Radar%20(SAR)%20Simulator">a</a>\n'
            '- [B](projects/Plain%20One/README.md)\n<a href="https://x/projects/Dup">c</a><a href="https://x/projects/Dup">c</a>')
    assert P.parse_megatrend_links(text) == ["Synthetic Aperture Radar (SAR) Simulator", "Dup", "Plain One"]


def test_r7_modeling_modelling_variants_match(tmp_path):
    (tmp_path / "megatrends").mkdir()
    (tmp_path / "megatrends" / "Big Data.md").write_text('<a href="x/projects/Traffic%20Modeling">', encoding="utf-8")
    tm = load_trend_map(tmp_path)
    assert tm[P.norm_key("Traffic Modelling")] == ["Big Data"]


def test_r1_only_real_projects(synth_hub):
    cat = build_catalog(synth_hub)
    assert [p["id"] for p in cat] == ["777"]
    assert cat[0]["technology_trends"] == ["Drones"]


def test_r1_real_hub_count(catalog, hub):
    n = sum(1 for d in (hub / "projects").iterdir() if (d / "README.md").is_file())
    assert len(catalog) == n == 83
    titles = [p["title"] for p in catalog]
    assert not any("ALL_SUBMISSIONS" in p["source_file"] or "submissions" in p["source_file"] for p in catalog)
    assert "Traffic Data Analysis for Modelling and Prediction of Traffic Scenarios" in titles or \
        any("Traffic Data Analysis" in t for t in titles)


def test_real_page_palletizing(catalog):
    p = next(x for x in catalog if x["id"] == "254")
    assert p["title"] == "Adaptive Palletizing with Simulation Optimization"
    assert p["academic_levels"] == ["Bachelor", "Master's"]
    assert p["expertise_gained_original"] == ["Robotics", "Manipulators", "Modeling and Simulation", "Optimization"]
    assert p["partners"] == ["Universal Robots"] and p["partner_type"] == "industry"
    assert "Robotics" in p["technology_trends"]
    assert "Robotics System Toolbox" in p["mathworks_products"]
    assert p["mathworks_platforms"] == ["MATLAB", "Simulink"]
    assert p["thumbnail"].endswith("UR.png")


def test_r7_sar_project_gets_trend_despite_parentheses(catalog):
    p = next(x for x in catalog if x["title"].startswith("Synthetic Aperture Radar"))
    assert p["technology_trends"]
