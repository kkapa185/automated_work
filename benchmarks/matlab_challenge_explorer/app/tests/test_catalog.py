import json
import re
import subprocess
import sys
from pathlib import Path

from catalog_explorer import rules as R

ROOT = Path(__file__).resolve().parent.parent
FIELDS = ["id", "title", "project_url", "source_file", "summary", "technology_trends", "mathworks_platforms",
          "mathworks_products", "expertise_gained_original", "difficulty", "academic_levels", "project_type",
          "application_areas", "hardware_required", "hardware_tags", "has_partner", "partners", "partner_type",
          "thumbnail"]


def test_schema_and_enums_for_every_project(catalog):
    ids = set()
    for p in catalog:
        assert list(p) == FIELDS
        assert p["id"].isdigit() and p["id"] not in ids
        ids.add(p["id"])
        assert p["title"] and p["summary"] and p["expertise_gained_original"]
        assert re.fullmatch(r"https://github\.com/mathworks/MATLAB-Simulink-Challenge-Project-Hub/tree/main/projects/[^ ]+", p["project_url"])
        assert (ROOT / "hub" / p["source_file"]).is_file()
        assert p["difficulty"] in R.DIFFICULTIES
        assert p["hardware_required"] in R.HARDWARE_REQUIRED
        assert p["project_type"] and set(p["project_type"]) <= set(R.PROJECT_TYPES)
        assert p["application_areas"] and set(p["application_areas"]) <= set(R.APPLICATION_AREAS)
        assert p["mathworks_platforms"] and set(p["mathworks_platforms"]) <= {"MATLAB", "Simulink"}
        assert p["has_partner"] == bool(p["partners"])
        assert p["partner_type"] == ("industry" if p["has_partner"] else "")
        if p["hardware_tags"]:
            assert p["hardware_required"] != "None"
        assert len({x.lower() for x in p["expertise_gained_original"]}) == len(p["expertise_gained_original"])
        assert p["thumbnail"].startswith("http")


def test_sorted_by_numeric_id(catalog):
    ids = [int(p["id"]) for p in catalog]
    assert ids == sorted(ids)


def test_trend_pages_and_partners_real(catalog):
    trends = {t for p in catalog for t in p["technology_trends"]}
    assert "Robotics" in trends and "Drones" in trends and "Neuroscience" not in trends
    assert sum(p["has_partner"] for p in catalog) >= 10
    assert any(p["hardware_required"] == "Required" for p in catalog)


def test_build_deterministic_cli(tmp_path):
    out1, out2 = tmp_path / "a" / "b" / "p.json", tmp_path / "p2.json"
    for o in (out1, out2):
        r = subprocess.run([str(ROOT / "catalog"), "build", str(ROOT / "hub"), "-o", str(o)], capture_output=True, text=True, cwd=tmp_path)
        assert r.returncode == 0, r.stderr
    assert out1.read_bytes() == out2.read_bytes()
    data = json.loads(out1.read_text(encoding="utf-8"))
    assert len(data) == 83


def test_cli_missing_hub(tmp_path):
    r = subprocess.run([sys.executable, str(ROOT / "catalog"), "build", str(tmp_path / "nope"), "-o", str(tmp_path / "o.json")],
                       capture_output=True, text=True)
    assert r.returncode == 2 and "error" in r.stderr
    r = subprocess.run([sys.executable, str(ROOT / "catalog"), "--help"], capture_output=True, text=True)
    assert r.returncode == 0 and "serve" in r.stdout


def test_synthetic_full_record(synth_hub):
    from catalog_explorer.catalog import build_catalog
    p = build_catalog(synth_hub)[0]
    assert p["expertise_gained_original"] == ["Drones", "Robotics", "Control", "Machine Learning"]
    assert p["academic_levels"] == ["Master's", "Doctoral"] and p["difficulty"] == "Advanced"
    assert p["mathworks_products"] == ["Deep Learning Toolbox"]
    assert p["mathworks_platforms"] == ["MATLAB", "Simulink"]
    assert p["hardware_tags"] == ["Raspberry Pi"] and p["hardware_required"] == "Optional"
    assert p["partners"] == ["Acme Robotics"] and p["has_partner"]
    assert "Aerospace" in p["application_areas"] and "AI / Machine Learning" in p["project_type"]


def test_r16_unreadable_readme_is_skipped(synth_hub, capsys):
    import os
    from catalog_explorer.catalog import build_catalog
    bad = synth_hub / "projects" / "Bad"
    bad.mkdir()
    (bad / "README.md").write_bytes(b"\xff\xfe## Project Number\n\n5\n")  # invalid UTF-8 is tolerated
    cat = build_catalog(synth_hub)
    assert {p["id"] for p in cat} >= {"777"}


def test_cli_serve_port_in_use_and_bad_output(tmp_path):
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen(1)
    port = s.getsockname()[1]
    r = subprocess.run([str(ROOT / "catalog"), "serve", str(ROOT / "hub"), "--port", str(port)], capture_output=True, text=True, timeout=60)
    s.close()
    assert r.returncode == 1 and "cannot listen" in r.stderr
    blocker = tmp_path / "f"
    blocker.write_text("x")
    r = subprocess.run([str(ROOT / "catalog"), "build", str(ROOT / "hub"), "-o", str(blocker / "o.json")], capture_output=True, text=True)
    assert r.returncode == 1 and "error" in r.stderr
