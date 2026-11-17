import json
import threading
import urllib.request
from pathlib import Path

import pytest

from catalog_explorer.catalog import build_catalog
from catalog_explorer.server import make_server

ROOT = Path(__file__).resolve().parent.parent
HUB = ROOT / "hub"

SYNTH_PAGE = """Fill out this <strong>[form](https://www.mathworks.com/x?tfa_1=T&tfa_2=777)</strong> to register.\r
\r
This project is developed in collaboration with **Acme Robotics, Inc.**\r
\r
<table>\r
<td><img src="https://example.com/pic.png"  width=500 /></td>\r
<td><p><h1>Synthetic &amp; Test Project</h1></p>\r
<p>Build a thing with MATLAB. It is a second sentence.</p>\r
</table>\r
\r
## Motivation\r
\r
Text.\r
\r
## Project Description\r
\r
Use [Deep Learning Toolbox](https://www.mathworks.com/products/deep-learning.html) and Simulink to train a neural network\r
for a quadrotor drone controller. Deploy to a Raspberry Pi board.\r
\r
## Impact\r
\r
Better drones.\r
\r
## Expertise Gained\r
\r
Drones, Robotics,  Control , drones, Machine Learning\r
\r
## Project Difficulty\r
\r
Master’s level, Doctoral\r
\r
## Project Number\r
\r
777\r
"""


@pytest.fixture(scope="session")
def hub():
    return HUB


@pytest.fixture(scope="session")
def catalog():
    return build_catalog(HUB)


@pytest.fixture()
def synth_hub(tmp_path):
    """A tiny synthetic hub with two projects, one trend page and a non-project folder."""
    (tmp_path / "projects" / "Synthetic Project").mkdir(parents=True)
    (tmp_path / "projects" / "Synthetic Project" / "README.md").write_text(SYNTH_PAGE, encoding="utf-8")
    (tmp_path / "projects" / "Only Submissions").mkdir()
    (tmp_path / "projects" / "Only Submissions" / "submissions.md").write_text("# s", encoding="utf-8")
    (tmp_path / "projects" / "ALL_SUBMISSIONS.md").write_text("# all", encoding="utf-8")
    (tmp_path / "megatrends").mkdir()
    (tmp_path / "megatrends" / "Drones.md").write_text(
        '<a href="https://github.com/x/y/blob/main/projects/Synthetic%20Project">x</a>', encoding="utf-8")
    return tmp_path


@pytest.fixture(scope="session")
def server(catalog):
    httpd = make_server(catalog, "127.0.0.1", 0)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


def http_get(url):
    try:
        with urllib.request.urlopen(url) as r:
            return r.status, r.headers, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read()


@pytest.fixture(scope="session")
def get_json(server):
    def _get(path):
        status, headers, body = http_get(server + path)
        return status, json.loads(body)
    return _get
