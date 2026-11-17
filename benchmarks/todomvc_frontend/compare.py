"""Run the same TodoMVC e2e suite against the reference vanilla-JS example and the generated app."""
import argparse
import functools
import http.server
import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from common import check, finish, run  # noqa: E402


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def e2e(base):
    r = run(["node", str(HERE / "e2e.js"), base], timeout=900, env=dict(os.environ, NODE_PATH="/opt/node22/lib/node_modules"))
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except Exception:  # noqa: BLE001
        return [{"name": "suite", "passed": False, "detail": r.stderr[-400:]}]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", required=True)
    ap.add_argument("--reference", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    ref_dir = Path(a.reference) / "examples" / "javascript-es6" / "dist"
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(ref_dir))
    handler.log_message = lambda *x: None
    rs = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=rs.serve_forever, daemon=True).start()
    ref_results = {r["name"]: r["passed"] for r in e2e(f"http://127.0.0.1:{rs.server_address[1]}")}
    rs.shutdown()
    checks = []
    port = free_port()
    try:
        srv = subprocess.Popen(["./serve", "--port", str(port)], cwd=a.app, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError as exc:
        checks.append(check("./serve starts", False, repr(exc)))
        return finish(a.out, checks)
    try:
        up = False
        for _ in range(40):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=2)
                up = True
                break
            except Exception:  # noqa: BLE001
                time.sleep(0.5)
        checks.append(check("./serve serves the app", up))
        if up:
            for r in e2e(f"http://127.0.0.1:{port}"):
                ref_ok = ref_results.get(r["name"])
                checks.append(check(f"{r['name']} (reference: {'pass' if ref_ok else 'FAIL'})", r["passed"], r.get("detail", "")))
    finally:
        try:
            os.killpg(srv.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        srv.wait(timeout=10)
    finish(a.out, checks, reference=ref_results)


if __name__ == "__main__":
    main()
