"""A scriptable stand-in for the ``claude`` CLI used by the test-suite.

Behaviour is driven by a JSON scenario file (``FAKE_CLAUDE_SCENARIO``)::

    {"session_id": "sess-1",
     "calls": [ {<call spec>}, ... ],      # consumed in order, one per invocation
     "default": {<call spec>}}             # used once ``calls`` is exhausted

Call spec keys (all optional):
    write: {relative_path: content}  files written into the cwd before replying
    result: str                      the ``result`` text
    session_id: str                  override the session id in the reply
    is_error: bool, subtype: str
    exit_code: int                   process exit status (default 0)
    stderr: str                      text written to stderr
    raw_stdout: str                  print this instead of the JSON payload
    preamble: str                    a non-JSON line printed before the payload
    sleep: float                     seconds to sleep before replying
    spawn_child: bool                fork a long-lived grandchild and record its pid
    usage: {...}, cost: float

Every invocation appends ``{"argv", "cwd", "stdin"}`` to ``FAKE_CLAUDE_LOG`` (JSONL).
"""

import json
import os
import subprocess
import sys
import time


def main() -> int:
    argv = sys.argv[1:]
    log_path = os.environ["FAKE_CLAUDE_LOG"]
    with open(os.environ["FAKE_CLAUDE_SCENARIO"]) as fh:
        scenario = json.load(fh)
    try:
        with open(log_path) as fh:
            index = sum(1 for _ in fh)
    except FileNotFoundError:
        index = 0

    stdin_text = None
    if "-p" in argv:
        i = argv.index("-p")
        if i + 1 >= len(argv) or argv[i + 1].startswith("--"):
            stdin_text = sys.stdin.read()

    with open(log_path, "a") as fh:
        fh.write(json.dumps({"argv": argv, "cwd": os.getcwd(), "stdin": stdin_text, "pid": os.getpid()}) + "\n")

    calls = scenario.get("calls", [])
    spec = calls[index] if index < len(calls) else scenario.get("default", {})

    # Emulate `--session-id`: the session is created as soon as the CLI starts; reusing an id fails.
    sessions_file = log_path + ".sessions"
    if "--session-id" in argv and "--resume" not in argv:
        wanted = argv[argv.index("--session-id") + 1]
        try:
            existing = open(sessions_file).read().split()
        except FileNotFoundError:
            existing = []
        if wanted in existing:
            sys.stderr.write(f"Error: Session ID {wanted} is already in use.\n")
            return 1
        if not spec.get("crash_before_session"):
            with open(sessions_file, "a") as fh:
                fh.write(wanted + "\n")
        else:
            sys.stderr.write("fatal: crashed during startup ECONNRESET\n")
            return 1

    if spec.get("spawn_child"):
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])
        with open(log_path + ".children", "a") as fh:
            fh.write(f"{child.pid}\n")
    if spec.get("sleep"):
        time.sleep(float(spec["sleep"]))

    for rel, content in (spec.get("write") or {}).items():
        path = os.path.join(os.getcwd(), rel)
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w") as fh:
            fh.write(content)

    if spec.get("stderr"):
        sys.stderr.write(spec["stderr"])
        sys.stderr.flush()

    if "raw_stdout" in spec:
        sys.stdout.write(spec["raw_stdout"])
    else:
        if "--resume" in argv:
            sid = argv[argv.index("--resume") + 1]
        elif "--session-id" in argv:
            sid = argv[argv.index("--session-id") + 1]
        else:
            sid = scenario.get("session_id", "fake-session-0001")
        sid = spec.get("session_id", sid)
        if spec.get("preamble"):
            print(spec["preamble"])
        payload = {
            "type": "result",
            "subtype": spec.get("subtype", "error_during_execution" if spec.get("is_error") else "success"),
            "is_error": bool(spec.get("is_error", False)),
            "result": spec.get("result", f"turn {index + 1} done"),
            "session_id": sid,
            "num_turns": 3,
            "duration_ms": 10,
            "total_cost_usd": spec.get("cost", 0.01),
            "usage": spec.get("usage", {"input_tokens": 100, "output_tokens": 50,
                                         "cache_creation_input_tokens": 0, "cache_read_input_tokens": 10}),
        }
        print(json.dumps(payload))
    sys.stdout.flush()
    return int(spec.get("exit_code", 0))


if __name__ == "__main__":
    sys.exit(main())
