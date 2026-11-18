"""Replay identical command scripts against the reference redis-server and the generated ./serve."""
import argparse
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from common import check, finish, run  # noqa: E402


class Conn:
    def __init__(self, port):
        self.s = socket.create_connection(("127.0.0.1", port), timeout=10)
        self.f = self.s.makefile("rb")

    def send(self, *args):
        out = b"*%d\r\n" % len(args)
        for a in args:
            a = a if isinstance(a, bytes) else str(a).encode()
            out += b"$%d\r\n%s\r\n" % (len(a), a)
        self.s.sendall(out)

    def read(self):
        line = self.f.readline()
        if not line:
            raise ConnectionError("closed")
        t, rest = line[:1], line[1:-2]
        if t == b"+":
            return rest.decode()
        if t == b"-":
            return ("ERR", rest.decode().split(" ")[0])  # compare error class only
        if t == b":":
            return int(rest)
        if t == b"$":
            n = int(rest)
            if n < 0:
                return None
            data = self.f.read(n + 2)[:-2]
            return data.decode(errors="replace")
        if t == b"*":
            n = int(rest)
            return None if n < 0 else [self.read() for _ in range(n)]
        raise ValueError(f"bad reply {line!r}")

    def cmd(self, *args):
        self.send(*args)
        return self.read()


UNORDERED = {"SMEMBERS", "SINTER", "SUNION", "SDIFF", "KEYS", "HKEYS", "HVALS", "PUBSUB"}
PAIRS = {"HGETALL"}


def normalize(cmd, reply):
    name = cmd[0].upper()
    if isinstance(reply, list):
        if name in UNORDERED:
            return sorted(reply, key=repr)
        if name in PAIRS:
            return sorted(zip(reply[::2], reply[1::2]))
    return reply


SCRIPT = [
    ["PING"], ["ECHO", "hi"], ["SET", "s", "v"], ["GET", "s"], ["GET", "missing"], ["SET", "s", "w", "NX"], ["SET", "s", "w", "XX", "GET"],
    ["GET", "s"], ["APPEND", "s", "xyz"], ["STRLEN", "s"], ["GETRANGE", "s", "1", "-2"], ["SETRANGE", "s", "10", "Z"], ["GET", "s"],
    ["SET", "n", "10"], ["INCR", "n"], ["INCRBY", "n", "-5"], ["DECR", "n"], ["INCRBYFLOAT", "n", "1.5"], ["GET", "n"], ["INCR", "s"],
    ["SET", "big", "9223372036854775807"], ["INCR", "big"], ["MSET", "a", "1", "b", "2"], ["MGET", "a", "b", "nope"], ["MSETNX", "a", "9", "c", "3"],
    ["GETSET", "a", "100"], ["GETDEL", "b"], ["EXISTS", "a", "b", "a"], ["DEL", "a", "c", "zz"], ["TYPE", "s"], ["TYPE", "nothing"],
    ["GET"], ["SET", "x"], ["NOSUCHCOMMAND"],
    ["RPUSH", "L", "a", "b", "c"], ["LPUSH", "L", "z"], ["LRANGE", "L", "0", "-1"], ["LLEN", "L"], ["LINDEX", "L", "-1"], ["LSET", "L", "1", "A"],
    ["LINSERT", "L", "BEFORE", "c", "bb"], ["LRANGE", "L", "0", "-1"], ["LREM", "L", "0", "bb"], ["LPOP", "L"], ["RPOP", "L", "2"], ["LRANGE", "L", "0", "-1"],
    ["RPUSH", "L2", "1", "2", "3", "2", "1"], ["LPOS", "L2", "2"], ["LPOS", "L2", "2", "RANK", "-1"], ["LTRIM", "L2", "1", "3"], ["LRANGE", "L2", "0", "-1"],
    ["LMOVE", "L2", "L3", "LEFT", "RIGHT"], ["LRANGE", "L3", "0", "-1"], ["GET", "L2"], ["LPUSHX", "nolist", "x"], ["LRANGE", "nolist", "0", "-1"],
    ["HSET", "H", "f1", "v1", "f2", "v2"], ["HGET", "H", "f1"], ["HMGET", "H", "f1", "zz"], ["HGETALL", "H"], ["HINCRBY", "H", "cnt", "5"],
    ["HINCRBYFLOAT", "H", "cnt", "0.5"], ["HDEL", "H", "f2", "zz"], ["HLEN", "H"], ["HEXISTS", "H", "f1"], ["HKEYS", "H"], ["HSETNX", "H", "f1", "x"], ["HSTRLEN", "H", "f1"],
    ["SADD", "S1", "a", "b", "c"], ["SADD", "S2", "b", "c", "d"], ["SADD", "S1", "a"], ["SCARD", "S1"], ["SISMEMBER", "S1", "a"], ["SMISMEMBER", "S1", "a", "z"],
    ["SINTER", "S1", "S2"], ["SUNION", "S1", "S2"], ["SDIFF", "S1", "S2"], ["SINTERSTORE", "S3", "S1", "S2"], ["SMEMBERS", "S3"], ["SREM", "S1", "a", "z"],
    ["SMOVE", "S1", "S2", "b"], ["SMEMBERS", "S2"], ["SINTERCARD", "2", "S1", "S2"],
    ["ZADD", "Z", "1", "a", "2", "b", "3.5", "c"], ["ZADD", "Z", "XX", "CH", "5", "a"], ["ZADD", "Z", "NX", "9", "a", "0", "d"], ["ZRANGE", "Z", "0", "-1", "WITHSCORES"],
    ["ZSCORE", "Z", "c"], ["ZINCRBY", "Z", "1.5", "b"], ["ZRANK", "Z", "b"], ["ZREVRANK", "Z", "b"], ["ZCARD", "Z"], ["ZCOUNT", "Z", "(1", "+inf"],
    ["ZRANGEBYSCORE", "Z", "-inf", "(5", "WITHSCORES", "LIMIT", "1", "2"], ["ZREVRANGE", "Z", "0", "1"], ["ZRANGE", "Z", "(5", "0", "BYSCORE", "REV"],
    ["ZADD", "ZL", "0", "a", "0", "b", "0", "c", "0", "d"], ["ZRANGEBYLEX", "ZL", "[b", "(d"], ["ZPOPMIN", "Z"], ["ZPOPMAX", "Z", "2"], ["ZMSCORE", "Z", "b", "nope"],
    ["ZADD", "Zw1", "1", "x", "2", "y"], ["ZADD", "Zw2", "10", "y", "20", "z"], ["ZUNIONSTORE", "Zu", "2", "Zw1", "Zw2", "WEIGHTS", "2", "1"], ["ZRANGE", "Zu", "0", "-1", "WITHSCORES"],
    ["ZINTERSTORE", "Zi", "2", "Zw1", "Zw2", "AGGREGATE", "MAX"], ["ZRANGE", "Zi", "0", "-1", "WITHSCORES"], ["ZADD", "Z", "nan", "q"], ["ZADD", "Z", "inf", "top"], ["ZSCORE", "Z", "top"],
    ["LPUSH", "H", "x"], ["SADD", "L3", "x"], ["HGET", "s", "x"],
    ["SET", "t", "1", "EX", "100"], ["TTL", "t"], ["PERSIST", "t"], ["TTL", "t"], ["TTL", "nokey"], ["EXPIRE", "t", "50"], ["PTTL", "t"] if False else ["EXISTS", "t"],
    ["RENAME", "t", "t2"], ["GET", "t2"], ["RENAMENX", "t2", "s"], ["RENAME", "nokey", "zz"], ["COPY", "t2", "t3"], ["GET", "t3"], ["OBJECT", "ENCODING", "n"] if False else ["PING"],
    ["SELECT", "1"], ["GET", "s"], ["SET", "db1key", "x"], ["DBSIZE"], ["SELECT", "0"], ["MOVE", "s", "1"], ["EXISTS", "s"], ["SELECT", "16"],
    ["MULTI"], ["SET", "m1", "1"], ["INCR", "m1"], ["LPUSH", "m1", "x"], ["EXEC"], ["GET", "m1"], ["MULTI"], ["SET", "m2", "1"], ["DISCARD"], ["GET", "m2"],
    ["MULTI"], ["SET", "m3"], ["SET", "m3", "ok"], ["EXEC"], ["GET", "m3"], ["EXEC"],
    ["KEYS", "S*"], ["DEL", "S1", "S2", "S3", "L", "L2", "L3", "H", "Z", "ZL", "Zu", "Zi", "Zw1", "Zw2", "n", "big", "t2", "t3", "m1", "m3"], ["KEYS", "*"], ["FLUSHALL"], ["DBSIZE"],
]


class Server:
    def __init__(self, argv, cwd, port):
        self.p = subprocess.Popen(argv, cwd=cwd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        self.port = port
        for _ in range(100):
            try:
                c = Conn(port)
                if c.cmd("PING") == "PONG":
                    return
            except OSError:
                time.sleep(0.2)
        raise RuntimeError("server did not start")

    def stop(self):
        try:
            os.killpg(self.p.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            self.p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(self.p.pid, signal.SIGKILL)


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start(kind, app, ref, d):
    port = free_port()
    if kind == "ref":
        return Server([str(ref / "src" / "redis-server"), "--port", str(port), "--dir", d, "--save", "", "--appendonly", "no"], d, port)
    return Server([str(app / "serve"), "--port", str(port), "--dir", d], str(app), port)


def scenario_script(port):
    c = Conn(port)
    return [normalize(cmd, c.cmd(*cmd)) for cmd in SCRIPT]


def scenario_expiry(port):
    c = Conn(port)
    out = [c.cmd("SET", "e1", "v", "PX", "300"), c.cmd("PEXPIRE", "e1", "250") ]
    time.sleep(0.6)
    out += [c.cmd("GET", "e1"), c.cmd("EXISTS", "e1"), c.cmd("SET", "e2", "v", "EX", "1"), c.cmd("SET", "e2", "w", "KEEPTTL")]
    time.sleep(1.3)
    out += [c.cmd("GET", "e2"), c.cmd("DBSIZE")]
    return out


def scenario_pubsub(port):
    sub, pub = Conn(port), Conn(port)
    out = [sub.cmd("SUBSCRIBE", "news", "sport")]
    out.append(sub.read())
    out.append(sub.cmd("PSUBSCRIBE", "w*"))
    time.sleep(0.2)
    out += [pub.cmd("PUBLISH", "news", "hello"), pub.cmd("PUBLISH", "weather", "rain"), pub.cmd("PUBLISH", "none", "x")]
    out += [sub.read(), sub.read()]
    out.append(sorted(pub.cmd("PUBSUB", "CHANNELS")))
    out.append(sub.cmd("UNSUBSCRIBE", "news"))
    return out


def scenario_blocking(port):
    a, b = Conn(port), Conn(port)
    res = {}
    t = threading.Thread(target=lambda: res.setdefault("r", a.cmd("BLPOP", "q", "5")))
    t.start()
    time.sleep(0.3)
    pushed = b.cmd("RPUSH", "q", "job1")
    t.join(6)
    timed = b.cmd("BLPOP", "empty", "0.3")
    return [pushed, res.get("r"), timed]


def scenario_watch(port):
    a, b = Conn(port), Conn(port)
    out = [a.cmd("SET", "w", "1"), a.cmd("WATCH", "w"), b.cmd("SET", "w", "2"), a.cmd("MULTI"), a.cmd("SET", "w", "3"), a.cmd("EXEC"), a.cmd("GET", "w")]
    out += [a.cmd("WATCH", "w"), a.cmd("MULTI"), a.cmd("INCR", "w"), a.cmd("EXEC")]
    return out


def scenario_pipeline(port):
    s = socket.create_connection(("127.0.0.1", port), timeout=10)
    s.sendall(b"PING\r\nSET p 1\r\n" + b"".join(b"*2\r\n$4\r\nINCR\r\n$1\r\np\r\n" for _ in range(100)) + b"GET p\r\n")
    data = b""
    deadline = time.time() + 5
    while time.time() < deadline and not data.endswith(b"$3\r\n101\r\n"):
        data += s.recv(65536)
    return data.endswith(b"$3\r\n101\r\n") and data.startswith(b"+PONG\r\n+OK\r\n:2\r\n")


def scenario_concurrency(port):
    def worker(i):
        c = Conn(port)
        for _ in range(200):
            c.cmd("INCR", "ctr")
        c.cmd("SADD", "who", str(i))
    ts = [threading.Thread(target=worker, args=(i,)) for i in range(50)]
    [t.start() for t in ts]
    [t.join(60) for t in ts]
    c = Conn(port)
    return [c.cmd("GET", "ctr"), c.cmd("SCARD", "who")]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", required=True)
    ap.add_argument("--reference", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    app, ref = Path(a.app).resolve(), Path(a.reference)
    checks = []
    results = {}
    for kind in ("ref", "app"):
        d = tempfile.mkdtemp()
        try:
            srv = start(kind, app, ref, d)
        except Exception as exc:  # noqa: BLE001
            results[kind] = None
            checks.append(check(f"{kind}: server starts", False, repr(exc)))
            continue
        res = {}
        for name, fn in (("script", scenario_script), ("expiry", scenario_expiry), ("pubsub", scenario_pubsub),
                         ("blocking", scenario_blocking), ("watch", scenario_watch), ("pipeline", scenario_pipeline),
                         ("concurrency", scenario_concurrency)):
            try:
                Conn(srv.port).cmd("FLUSHALL")
                res[name] = fn(srv.port)
            except Exception as exc:  # noqa: BLE001
                res[name] = f"EXC {exc!r}"
        # persistence
        try:
            c = Conn(srv.port)
            c.cmd("FLUSHALL"); c.cmd("SET", "keep", "me"); c.cmd("HSET", "kh", "a", "1"); c.cmd("ZADD", "kz", "2", "m"); c.cmd("SET", "kt", "x", "EX", "1000")
            c.cmd("SAVE")
            srv.stop()
            srv = start(kind, app, ref, d)
            c = Conn(srv.port)
            res["persistence"] = [c.cmd("GET", "keep"), c.cmd("HGET", "kh", "a"), c.cmd("ZSCORE", "kz", "m"), c.cmd("TTL", "kt") > 900]
        except Exception as exc:  # noqa: BLE001
            res["persistence"] = f"EXC {exc!r}"
        # throughput
        if kind == "app":
            bench = run([str(ref / "src" / "redis-benchmark"), "-p", str(srv.port), "-n", "20000", "-c", "1", "-q", "-t", "set,get"], timeout=300)
            import re
            rps = [float(x) for x in re.findall(r"([\d.]+) requests per second", bench.stdout)]
            res["rps"] = rps
        srv.stop()
        shutil.rmtree(d, ignore_errors=True)
        results[kind] = res
    r, g = results.get("ref"), results.get("app")
    if r and g:
        for i, (cmd, rv) in enumerate(zip(SCRIPT, r["script"])):
            gv = g["script"][i] if isinstance(g["script"], list) and i < len(g["script"]) else "<missing>"
            checks.append(check(f"reply {i:03d} {' '.join(cmd)[:60]}", gv == rv, f"got {gv!r} expected {rv!r}"))
        for name in ("expiry", "pubsub", "blocking", "watch", "pipeline", "concurrency", "persistence"):
            checks.append(check(f"scenario {name} identical", g[name] == r[name], f"got {g[name]!r} expected {r[name]!r}"))
        checks.append(check(">= 10,000 GET/SET requests per second (single client)", g.get("rps") and min(g["rps"]) >= 10000, g.get("rps")))
    finish(a.out, checks)


if __name__ == "__main__":
    main()
