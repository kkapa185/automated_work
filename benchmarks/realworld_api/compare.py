"""Run the official RealWorld conformance collection (Bruno, generated from the Hurl suite) against ./serve."""
import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from common import check, finish, run  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", required=True)
    ap.add_argument("--reference", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    bruno = Path(a.reference) / "specs" / "api" / "bruno"
    checks = []
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    try:
        srv = subprocess.Popen(["./serve", "--port", str(port)], cwd=a.app, stdout=subprocess.DEVNULL,
                               stderr=subprocess.PIPE, start_new_session=True)
    except OSError as exc:
        checks.append(check("./serve starts", False, repr(exc)))
        return finish(a.out, checks)
    up = False
    for _ in range(60):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/tags", timeout=2)
            up = True
            break
        except urllib.error.HTTPError:
            up = True
            break
        except Exception:  # noqa: BLE001
            time.sleep(1)
    checks.append(check("./serve starts and answers /api/tags", up))
    totals = {"passed": 0, "total": 0}
    try:
        if up:
            folders = sorted(p.name for p in bruno.iterdir() if p.is_dir() and p.name != "environments")
            for folder in folders:
                with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
                    rep = tf.name
                r = run(["bru", "run", folder, "--env", "local", "--env-var", f"host=http://127.0.0.1:{port}",
                         "--sandbox", "safe", "--reporter-json", rep], cwd=bruno, timeout=600)
                try:
                    data = json.loads(Path(rep).read_text())
                    results = data[0]["results"] if isinstance(data, list) else data["results"]
                except Exception:  # noqa: BLE001
                    results = []
                for res in results:
                    name = res.get("test", {}).get("filename") or res.get("request", {}).get("url", "?")
                    asserts = (res.get("assertionResults") or []) + (res.get("testResults") or [])
                    ok = bool(res.get("response")) and not res.get("error") and all(x.get("status") == "pass" for x in asserts)
                    totals["total"] += 1
                    totals["passed"] += ok
                    fails = [x.get("error") or x.get("description") for x in asserts if x.get("status") != "pass"][:2]
                    checks.append(check(f"{folder}/{Path(str(name)).name}", ok, fails or res.get("error", "")))
                if not results:
                    checks.append(check(f"{folder}: collection ran", False, (r.stdout[-300:] + r.stderr[-300:])))
    finally:
        try:
            os.killpg(srv.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        srv.wait(timeout=15)
    finish(a.out, checks, conformance=totals)


if __name__ == "__main__":
    main()
