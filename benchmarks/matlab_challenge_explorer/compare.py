"""Hidden acceptance harness: compare the generated catalog/explorer with the hub's curated projects.json + explorer."""
import argparse
import json
import socket
import subprocess


class _Failed:
    def __init__(self, exc):
        self.returncode, self.stdout, self.stderr = -1, "", repr(exc)


def run(*args, **kw):
    """subprocess.run that reports a missing/broken entry point as a failed check instead of crashing."""
    try:
        return subprocess.run(*args, **kw)
    except (OSError, subprocess.SubprocessError) as exc:
        return _Failed(exc)
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent


def jacc(a, b) -> float:
    a = {str(x).strip().lower() for x in (a or [])}
    b = {str(x).strip().lower() for x in (b or [])}
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


def get(url):
    with urllib.request.urlopen(url, timeout=20) as r:
        return json.loads(r.read())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", required=True)
    ap.add_argument("--reference", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    app, ref = Path(a.app), Path(a.reference)
    truth = json.loads((ref / "projects" / "projects.json").read_text())
    checks, fields = [], {}
    out = app / "_bench_out" / "projects.json"
    out.parent.mkdir(exist_ok=True)
    p = run(["./catalog", "build", "hub", "-o", str(out)], cwd=app, capture_output=True, text=True, timeout=600)
    checks.append({"name": "build exits 0", "passed": p.returncode == 0, "detail": p.stderr[-400:]})
    got = json.loads(out.read_text()) if out.exists() else []
    by_id = {str(x.get("id")): x for x in got if isinstance(x, dict)}
    ids_t = {x["id"] for x in truth}
    recall = len(ids_t & by_id.keys()) / len(ids_t)
    precision = len(ids_t & by_id.keys()) / max(1, len(by_id))
    checks.append({"name": "project ids: recall >= 0.98 and precision >= 0.98", "passed": recall >= 0.98 and precision >= 0.98,
                   "detail": f"recall={recall:.3f} precision={precision:.3f} got={len(got)} truth={len(truth)}"})
    agree = {k: [] for k in ["title", "difficulty", "technology_trends", "mathworks_platforms", "mathworks_products",
                             "expertise_gained_original", "partners", "hardware_required", "project_type", "application_areas"]}
    for t in truth:
        g = by_id.get(t["id"])
        for k in agree:
            if g is None:
                agree[k].append(0.0)
            elif isinstance(t[k], list):
                agree[k].append(jacc(g.get(k), t[k]))
            else:
                agree[k].append(float(str(g.get(k, "")).strip().lower() == str(t[k]).strip().lower()))
    thresholds = {"title": 0.98, "technology_trends": 0.85, "mathworks_platforms": 0.85, "expertise_gained_original": 0.85,
                  "partners": 0.9, "mathworks_products": 0.6, "difficulty": 0.6, "hardware_required": 0.5,
                  "project_type": 0.4, "application_areas": 0.4}
    for k, vals in agree.items():
        m = sum(vals) / len(vals)
        fields[k] = round(m, 4)
        checks.append({"name": f"field agreement {k} >= {thresholds[k]}", "passed": m >= thresholds[k], "detail": f"mean={m:.3f}"})

    # ---- explorer service
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    try:
        srv = subprocess.Popen(["./catalog", "serve", "hub", "--port", str(port)], cwd=app, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError as exc:
        checks.append({"name": "serve starts and answers /api/facets", "passed": False, "detail": repr(exc)})
        srv = None
    base = f"http://127.0.0.1:{port}"
    try:
        up = False
        for _ in range(60 if srv else 0):
            try:
                get(base + "/api/facets")
                up = True
                break
            except Exception:  # noqa: BLE001
                time.sleep(1)
        if srv:
            checks.append({"name": "serve starts and answers /api/facets", "passed": up, "detail": base})
        if up:
            allp = get(base + "/api/projects")
            checks.append({"name": "/api/projects count equals catalog size", "passed": allp.get("count") == len(got),
                           "detail": f"{allp.get('count')} vs {len(got)}"})
            gen_by_diff = {}
            for x in got:
                gen_by_diff[x.get("difficulty")] = gen_by_diff.get(x.get("difficulty"), 0) + 1
            d = get(base + "/api/projects?difficulty=Advanced")
            checks.append({"name": "difficulty filter consistent with catalog", "passed": d.get("count") == gen_by_diff.get("Advanced", 0),
                           "detail": f"{d.get('count')} vs {gen_by_diff.get('Advanced', 0)}"})
            rob_truth = sum(1 for x in truth if "Robotics" in x["technology_trends"] and "Advanced" == x["difficulty"])
            r = get(base + "/api/projects?technology_trend=Robotics&difficulty=Advanced")
            checks.append({"name": "combined filters (Robotics & Advanced) close to reference explorer", "passed": abs(r.get("count", -99) - rob_truth) <= 3,
                           "detail": f"{r.get('count')} vs reference {rob_truth}"})
            q = get(base + "/api/projects?q=reinforcement%20learning")
            q_truth = sum(1 for x in truth if "reinforcement learning" in (x["title"] + " " + " ".join(x["expertise_gained_original"])).lower())
            checks.append({"name": "full-text search finds reinforcement-learning projects", "passed": q.get("count", 0) >= q_truth,
                           "detail": f"{q.get('count')} (reference title/expertise matches: {q_truth})"})
            one = get(base + f"/api/projects/{truth[0]['id']}")
            checks.append({"name": "GET /api/projects/<id>", "passed": str(one.get("id")) == truth[0]["id"], "detail": str(one.get("title"))[:80]})
            try:
                urllib.request.urlopen(base + "/api/projects/999999", timeout=10)
                nf = False
            except urllib.error.HTTPError as e:
                nf = e.code == 404
            checks.append({"name": "unknown id -> 404", "passed": nf, "detail": ""})
            ui = run(["node", str(HERE / "explorer_check.js"), base], capture_output=True, text=True, timeout=180)
            try:
                u = json.loads(ui.stdout.strip().splitlines()[-1])
            except Exception:  # noqa: BLE001
                u = {"load": False, "errors": [ui.stderr[-300:]]}
            checks.append({"name": "explorer UI renders one card per project", "passed": u.get("load") and u.get("cards") == len(got) and not u.get("errors"),
                           "detail": json.dumps(u)[:300]})
            checks.append({"name": "explorer honours ?difficulty= URL state", "passed": u.get("filtered_cards") == gen_by_diff.get("Beginner", 0),
                           "detail": f"{u.get('filtered_cards')} vs {gen_by_diff.get('Beginner', 0)}"})
            checks.append({"name": "explorer search box filters cards", "passed": u.get("search_cards") is not None and 0 < u["search_cards"] < len(got),
                           "detail": str(u.get("search_cards"))})
    finally:
        import os, signal
        if srv:
            try:
                os.killpg(srv.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            srv.wait(timeout=10)
    score = sum(c["passed"] for c in checks) / len(checks)
    res = {"score": round(score, 4), "checks": checks, "field_agreement": fields}
    Path(a.out).write_text(json.dumps(res, indent=2))
    print(json.dumps({"score": res["score"], "field_agreement": fields, "failed": [c["name"] for c in checks if not c["passed"]]}, indent=2))


if __name__ == "__main__":
    main()
