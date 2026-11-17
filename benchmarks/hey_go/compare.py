"""Run reference hey and generated hey against an instrumented local server; compare observable behaviour."""
import argparse
import base64
import http.server
import re
import socketserver
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from common import check, finish, run  # noqa: E402


class Recorder:
    def __init__(self):
        self.reset()

    def reset(self):
        self.requests, self.connections = [], 0
        self.lock = threading.Lock()


REC = Recorder()


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def setup(self):
        super().setup()
        with REC.lock:
            REC.connections += 1

    def _do(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n) if n else b""
        with REC.lock:
            REC.requests.append({"method": self.command, "path": self.path, "headers": dict(self.headers), "body": body})
        if self.path.startswith("/redirect"):
            self.send_response(302)
            self.send_header("Location", "/final")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        code = 500 if self.path.startswith("/fail") and len(REC.requests) % 2 else 200
        payload = b"x" * 123
        self.send_response(code)
        self.send_header("Content-Length", str(len(payload)) if self.command != "HEAD" else "123")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(payload)

    do_GET = do_POST = do_PUT = do_DELETE = do_HEAD = do_OPTIONS = _do

    def log_message(self, *a):
        pass


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True


def sections(out: str):
    return [l.rstrip(":") for l in out.splitlines() if l and not l.startswith(" ") and l.endswith(":")]


def scenario(binary, args, base):
    REC.reset()
    t0 = time.time()
    r = run([str(binary), *args], timeout=120)
    return r, time.time() - t0, list(REC.requests), REC.connections


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", required=True)
    ap.add_argument("--reference", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    app, ref = Path(a.app), Path(a.reference)
    checks = []
    b = run(["go", "build", "-o", "hey", "."], cwd=app, timeout=900)
    checks.append(check("go build -o hey .", b.returncode == 0, b.stderr[-400:]))
    run(["go", "build", "-o", "hey_ref", "."], cwd=ref, timeout=900)
    gen, refb = app / "hey", ref / "hey_ref"
    if b.returncode != 0:
        return finish(a.out, checks)
    srv = Server(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        cases = {
            "default summary": ["-n", "40", "-c", "4", base + "/"],
            "method/headers/body": ["-n", "6", "-c", "2", "-m", "POST", "-H", "X-Test: 1", "-H", "X-Other: two", "-d", "hello body",
                                    "-T", "application/json", "-A", "text/plain", base + "/post"],
            "basic auth + host": ["-n", "3", "-c", "1", "-a", "user:pass", "-host", "example.test", base + "/auth"],
            "HEAD": ["-n", "5", "-c", "5", "-m", "HEAD", base + "/head"],
            "errors (500s)": ["-n", "20", "-c", "2", base + "/fail"],
            "no keepalive": ["-n", "12", "-c", "3", "-disable-keepalive", base + "/nk"],
            "redirects followed": ["-n", "4", "-c", "1", base + "/redirect"],
            "redirects disabled": ["-n", "4", "-c", "1", "-disable-redirects", base + "/redirect"],
        }
        for name, args in cases.items():
            rr, rt, rreq, rconn = scenario(refb, args, base)
            gr, gt, greq, gconn = scenario(gen, args, base)
            checks.append(check(f"{name}: exit status", gr.returncode == rr.returncode, f"{gr.returncode} vs {rr.returncode} {gr.stderr[-200:]}"))
            checks.append(check(f"{name}: same number of requests reach the server", len(greq) == len(rreq), f"{len(greq)} vs {len(rreq)}"))
            same_shape = sorted((q["method"], q["path"], q["body"]) for q in greq) == sorted((q["method"], q["path"], q["body"]) for q in rreq)
            checks.append(check(f"{name}: identical methods/paths/bodies", same_shape))
            keys = ("Content-Type", "Accept", "X-Test", "X-Other", "Authorization", "Host", "User-Agent")
            hdr = lambda reqs: sorted({tuple((k, (q["headers"].get(k) or "").split("/")[0] if k == "User-Agent" else q["headers"].get(k)) for k in keys) for q in reqs})
            checks.append(check(f"{name}: identical request headers", hdr(greq) == hdr(rreq), f"{hdr(greq)[:1]} vs {hdr(rreq)[:1]}"))
            checks.append(check(f"{name}: same report sections", sections(gr.stdout) == sections(rr.stdout), f"{sections(gr.stdout)} vs {sections(rr.stdout)}"))
            sc = lambda out: sorted(re.findall(r"\[(\d{3})\]\s+(\d+) responses", out))
            checks.append(check(f"{name}: identical status code distribution", sc(gr.stdout) == sc(rr.stdout), f"{sc(gr.stdout)} vs {sc(rr.stdout)}"))
            td = lambda out: re.findall(r"(Total data|Size/request):\s+(\d+) bytes", out)
            checks.append(check(f"{name}: identical Total data / Size/request", td(gr.stdout) == td(rr.stdout), f"{td(gr.stdout)} vs {td(rr.stdout)}"))
            if name == "no keepalive":
                checks.append(check("no keepalive: one TCP connection per request", gconn == len(greq) == rconn, f"{gconn} conns for {len(greq)} reqs (ref {rconn})"))
            if name == "default summary":
                hist = re.findall(r"^\s+\d+\.\d{3} \[(\d+)\]\s+\|", gr.stdout, re.M)
                checks.append(check("histogram: 11 buckets summing to n", len(hist) == 11 and sum(map(int, hist)) == 40, hist))
                checks.append(check("keep-alive reuses connections (<= c connections)", gconn <= 4, gconn))
        # CSV
        gr, *_ = scenario(gen, ["-n", "7", "-c", "1", "-o", "csv", base + "/csv"], base)
        rr, *_ = scenario(refb, ["-n", "7", "-c", "1", "-o", "csv", base + "/csv"], base)
        gl, rl = gr.stdout.strip().splitlines(), rr.stdout.strip().splitlines()
        checks.append(check("csv: identical header and 7 rows", gl[:1] == rl[:1] and len(gl) == len(rl) == 8, gl[:2]))
        # rate limiting and duration mode
        gr, gt, greq, _ = scenario(gen, ["-n", "10", "-c", "1", "-q", "5", base + "/q"], base)
        checks.append(check("-q 5 with 1 worker: 10 requests take ~2s", len(greq) == 10 and 1.5 <= gt <= 4.0, f"{gt:.2f}s {len(greq)} reqs"))
        gr, gt, greq, _ = scenario(gen, ["-z", "2s", "-c", "2", "-q", "10", base + "/z"], base)
        checks.append(check("-z 2s duration mode stops after ~2s", 1.8 <= gt <= 4.5 and 20 <= len(greq) <= 50, f"{gt:.2f}s {len(greq)} reqs"))
        for bad in (["-n", "2", "-c", "5", base], [], ["-m", "BREW", base], ["-H", "nocolon", base]):
            gr = run([str(gen), *bad], timeout=30)
            rr = run([str(refb), *bad], timeout=30)
            checks.append(check(f"usage edge case {bad[:4]} -> exit {rr.returncode} like reference", gr.returncode == rr.returncode, f"{gr.returncode} {gr.stderr[-120:]}"))
    finally:
        srv.shutdown()
    t = run(["go", "test", "./..."], cwd=app, timeout=900)
    checks.append(check("own go test ./... passes", t.returncode == 0, t.stdout[-300:]))
    finish(a.out, checks)


if __name__ == "__main__":
    main()
