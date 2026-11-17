"""R20-R25: API filters, facets, errors, UI smoke (over real HTTP)."""
import json
import re
import shutil
import subprocess
import threading
import urllib.request

import pytest

from tests.conftest import http_get


def test_r20_all_projects(get_json, catalog):
    status, body = get_json("/api/projects")
    assert status == 200 and body["count"] == len(catalog) == len(body["projects"])
    assert body["projects"] == catalog


def test_r21_single_filters(get_json, catalog):
    for param, field, value in [("difficulty", "difficulty", "Advanced"), ("hardware_required", "hardware_required", "Optional")]:
        _, body = get_json(f"/api/projects?{param}={value}")
        assert body["count"] == sum(p[field] == value for p in catalog) > 0
    _, body = get_json("/api/projects?technology_trend=Robotics")
    assert body["count"] == sum("Robotics" in p["technology_trends"] for p in catalog)
    _, body = get_json("/api/projects?platform=Simulink")
    assert body["count"] == sum("Simulink" in p["mathworks_platforms"] for p in catalog)
    _, body = get_json("/api/projects?project_type=Control%20Design")
    assert all("Control Design" in p["project_type"] for p in body["projects"]) and body["count"] > 0
    _, body = get_json("/api/projects?application_area=Automotive")
    assert all("Automotive" in p["application_areas"] for p in body["projects"]) and body["count"] > 0
    _, body = get_json("/api/projects?product=deep%20learning%20toolbox")  # case-insensitive
    assert body["count"] == sum("Deep Learning Toolbox" in p["mathworks_products"] for p in catalog) > 0


def test_r21_has_partner_and_partner(get_json, catalog):
    _, yes = get_json("/api/projects?has_partner=true")
    _, no = get_json("/api/projects?has_partner=false")
    assert yes["count"] + no["count"] == len(catalog) and yes["count"] > 0
    _, mc = get_json("/api/projects?partner=Microchip%20Technology")
    assert mc["count"] == 3
    assert get_json("/api/projects?has_partner=maybe")[0] == 400


def test_r21_or_within_and_across(get_json, catalog):
    _, both = get_json("/api/projects?difficulty=Beginner&difficulty=Advanced")
    assert both["count"] == sum(p["difficulty"] in ("Beginner", "Advanced") for p in catalog)
    _, anded = get_json("/api/projects?difficulty=Advanced&has_partner=false&platform=Simulink")
    assert anded["count"] == sum(p["difficulty"] == "Advanced" and not p["has_partner"] and "Simulink" in p["mathworks_platforms"] for p in catalog)
    _, none = get_json("/api/projects?difficulty=Beginner&hardware_required=Required&partner=Arm")
    assert none["count"] == 0 and none["projects"] == []


def test_r21_full_text_q(get_json, catalog):
    _, body = get_json("/api/projects?q=QUADROTOR")
    assert body["count"] > 0
    for p in body["projects"]:
        hay = " ".join([p["title"], p["summary"], *p["expertise_gained_original"], *p["mathworks_products"]]).lower()
        assert "quadrotor" in hay
    _, multi = get_json("/api/projects?q=deep%20learning")
    assert all("deep" in json.dumps(p).lower() for p in multi["projects"])
    _, products = get_json("/api/projects?q=robotics%20system%20toolbox")
    assert products["count"] > 0
    _, nothing = get_json("/api/projects?q=zzzzqqqq")
    assert nothing == {"count": 0, "projects": []}
    _, unknown = get_json("/api/projects?bogus=1")
    assert unknown["count"] == len(catalog)


def test_r22_single_project_and_errors(get_json, catalog):
    pid = catalog[0]["id"]
    status, body = get_json(f"/api/projects/{pid}")
    assert status == 200 and body == catalog[0]
    status, body = get_json("/api/projects/does-not-exist")
    assert status == 404 and "error" in body
    assert get_json("/nope")[0] == 404
    req = urllib.request.Request(get_json.__closure__[0].cell_contents + "/api/projects", method="POST")
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req)
    assert e.value.code == 405 and "error" in json.loads(e.value.read())


def test_r23_facets_counts(get_json, catalog):
    status, facets = get_json("/api/facets")
    assert status == 200
    assert set(facets) == {"difficulty", "technology_trend", "product", "platform", "project_type", "application_area",
                           "hardware_required", "partner", "has_partner"}
    d = {x["value"]: x["count"] for x in facets["difficulty"]}
    assert sum(d.values()) == len(catalog)
    t = {x["value"]: x["count"] for x in facets["technology_trend"]}
    assert t["Robotics"] == sum("Robotics" in p["technology_trends"] for p in catalog)
    prods = {x["value"]: x["count"] for x in facets["product"]}
    assert prods["Embedded Coder"] == sum("Embedded Coder" in p["mathworks_products"] for p in catalog)
    assert {x["value"]: x["count"] for x in facets["has_partner"]} == {
        "true": sum(p["has_partner"] for p in catalog), "false": sum(not p["has_partner"] for p in catalog)}
    counts = [x["count"] for x in facets["product"]]
    assert counts == sorted(counts, reverse=True)


def test_r23_facets_respect_filters_disjunctively(get_json, catalog):
    _, f = get_json("/api/facets?difficulty=Advanced&platform=Simulink")
    adv_sim = [p for p in catalog if p["difficulty"] == "Advanced" and "Simulink" in p["mathworks_platforms"]]
    # other groups are restricted by both filters
    hw = {x["value"]: x["count"] for x in f["hardware_required"]}
    assert sum(hw.values()) == len(adv_sim)
    # the difficulty group ignores its own filter so siblings keep their counts
    d = {x["value"]: x["count"] for x in f["difficulty"]}
    sim = [p for p in catalog if "Simulink" in p["mathworks_platforms"]]
    assert d["Advanced"] == sum(p["difficulty"] == "Advanced" for p in sim)
    assert d["Intermediate"] == sum(p["difficulty"] == "Intermediate" for p in sim)


def test_r25_content_types_and_head(server):
    status, headers, body = http_get(server + "/api/projects")
    assert headers["Content-Type"].startswith("application/json") and "utf-8" in headers["Content-Type"]
    status, headers, body = http_get(server + "/")
    assert headers["Content-Type"].startswith("text/html")


def test_r25_concurrent_requests(server):
    results = []

    def work():
        results.append(http_get(server + "/api/projects?q=robot")[0])

    ts = [threading.Thread(target=work) for _ in range(12)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert results == [200] * 12


def test_r24_ui_static_smoke(server):
    _, _, body = http_get(server + "/")
    html = body.decode()
    for needle in ['id="q"', 'id="facets"', 'id="chips"', 'id="count"', 'id="results"', "data-project-id",
                   "URLSearchParams", "pushState", "/api/projects", "/api/facets", "project_url", "textContent"]:
        assert needle in html, needle
    assert "innerHTML" not in html  # R24: no unsafe HTML injection
    assert not re.search(r'(src|href)="https?://', html)  # no external resources


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_r24_ui_runs_in_fake_dom(server, tmp_path):
    """Executes the page script against a minimal DOM and the live API; checks cards, facets, chips and URL state."""
    script = r"""
const base = process.argv[2];
const html = await (await fetch(base + '/')).text();
const js = html.match(/<script>([\s\S]*)<\/script>/)[1];
class El {
  constructor(t){this.tag=t;this.children=[];this.attrs={};this.listeners={};this.className='';this._text='';this.hidden=false;this.style={};}
  appendChild(c){this.children.push(c);return c;}
  setAttribute(k,v){this.attrs[k]=String(v);} getAttribute(k){return this.attrs[k];}
  addEventListener(t,f){(this.listeners[t]=this.listeners[t]||[]).push(f);}
  set textContent(v){this._text=String(v);this.children=[];} get textContent(){return this._text+this.children.map(c=>c.textContent).join('');}
  all(){return [this].concat(...this.children.map(c=>c.all()));}
  click(){(this.listeners.click||[]).forEach(f=>f());}
  change(){(this.listeners.change||[]).forEach(f=>f());}
}
const ids={};['q','facets','chips','count','results','empty'].forEach(i=>ids[i]=new El(i==='q'?'input':'div'));
const body=new El('body');
globalThis.document={getElementById:i=>ids[i],createElement:t=>new El(t),body};
let url='/'+(process.argv[3]||'');
const loc={get pathname(){return url.split('?')[0];},get search(){return url.includes('?')?'?'+url.split('?')[1]:'';}};
globalThis.location=loc;
globalThis.history={pushState:(a,b,u)=>{url=u;},replaceState:(a,b,u)=>{url=u;}};
globalThis.window={addEventListener(){}};
const realFetch=fetch;globalThis.fetch=(u,o)=>realFetch(base+u,o);
const wait=async()=>{for(let i=0;i<100;i++){await new Promise(r=>setTimeout(r,20));if(body.attrs['data-ready']){body.attrs['data-ready']=null;return;}}throw new Error('timeout');};
new Function(js)();
await wait();
const cards=()=>ids.results.children.filter(c=>c.attrs['data-project-id']);
const out={initial:cards().length,count:ids.count.textContent};
const cb=ids.facets.all().find(e=>e.attrs['data-facet']==='difficulty'&&e.value==='Advanced');
cb.checked=true;cb.change();await wait();
out.afterFilter=cards().length;out.url=url;out.chips=ids.chips.children.map(c=>c.textContent);
out.badges=cards().every(c=>c.all().some(e=>e.className==='badge Advanced'));
out.titleLinks=cards().every(c=>c.all().some(e=>e.tag==='a'&&e.href.startsWith('https://github.com/')));
ids.chips.children[0].click();await wait();
out.afterChip=cards().length;out.urlAfter=url;
console.log(JSON.stringify(out));
"""
    f = tmp_path / "ui.mjs"
    f.write_text(script)
    r = subprocess.run(["node", str(f), server, "?has_partner=false"], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout.strip().splitlines()[-1])
    _, _, body = http_get(server + "/api/projects?has_partner=false")
    n = json.loads(body)["count"]
    assert out["initial"] == n and out["count"].startswith(str(n))   # state restored from the URL
    assert 0 < out["afterFilter"] < n
    assert "difficulty=Advanced" in out["url"] and "has_partner=false" in out["url"]
    assert any("Advanced" in c for c in out["chips"])
    assert out["badges"] and out["titleLinks"]
    assert out["afterChip"] == n and "difficulty" not in out["urlAfter"]
