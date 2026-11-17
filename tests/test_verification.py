from __future__ import annotations

import json
import sys
from pathlib import Path

from schemas import CommandResult, VerificationReport
from verification import VerificationRunner, detect_commands


def test_detect_python(tmp_path: Path):
    (tmp_path / "tests").mkdir()
    cmds = detect_commands(tmp_path)
    assert len(cmds) == 1 and cmds[0].endswith("-m pytest -q")


def test_detect_pyproject_without_tests_runs_nothing(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    assert detect_commands(tmp_path) == []


def test_detect_node(tmp_path: Path):
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"test": "jest", "build": "tsc", "lint": "eslint ."}}))
    (tmp_path / "node_modules").mkdir()
    assert detect_commands(tmp_path) == ["npm run lint --silent", "npm run build --silent", "npm test --silent"]


def test_detect_node_placeholder_test_script_ignored(tmp_path: Path):
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"test": 'echo "Error: no test specified" && exit 1'}}))
    (tmp_path / "node_modules").mkdir()
    assert detect_commands(tmp_path) == []


def test_detect_rust_go_make(tmp_path: Path):
    (tmp_path / "Cargo.toml").write_text("")
    assert detect_commands(tmp_path) == ["cargo build --quiet", "cargo test --quiet"]
    (tmp_path / "Cargo.toml").unlink()
    (tmp_path / "go.mod").write_text("module x")
    assert detect_commands(tmp_path) == ["go vet ./...", "go test ./..."]
    (tmp_path / "go.mod").unlink()
    (tmp_path / "Makefile").write_text("test:\n\techo ok\n")
    assert detect_commands(tmp_path) == ["make test"]


def test_detect_empty(tmp_path: Path):
    assert detect_commands(tmp_path) == []


async def test_verify_real_pytest_pass_and_fail(tmp_path: Path):
    (tmp_path / "test_a.py").write_text("def test_ok():\n    assert 1 == 1\n")
    rep = await VerificationRunner().verify(str(tmp_path))
    assert rep.passed, rep.failure_digest()
    (tmp_path / "test_b.py").write_text("def test_bad():\n    assert 'left' == 'right'\n")
    rep = await VerificationRunner().verify(str(tmp_path))
    assert not rep.passed and rep.results[0].exit_code == 1
    assert "test_bad" in rep.failure_digest()


async def test_explicit_commands_all_must_pass(tmp_path: Path):
    ok = f'{sys.executable} -c "pass"'
    bad = f'{sys.executable} -c "import sys; sys.exit(2)"'
    rep = await VerificationRunner().verify(str(tmp_path), [ok, bad, ok])
    assert not rep.passed and [r.exit_code for r in rep.results] == [0, 2, 0]
    rep = await VerificationRunner().verify(str(tmp_path), [ok, bad, ok], stop_on_failure=True)
    assert len(rep.results) == 2


async def test_timeout(tmp_path: Path):
    rep = await VerificationRunner(timeout_s=0.5, kill_grace_s=0.2).verify(
        str(tmp_path), [f'{sys.executable} -c "import time; time.sleep(30)"'])
    assert not rep.passed and rep.results[0].timed_out
    assert "TIMED OUT" in rep.failure_digest()


async def test_missing_command_and_bad_quoting(tmp_path: Path):
    r = VerificationRunner()
    assert (await r.run_command("definitely-not-a-binary-xyz", str(tmp_path))).exit_code == 127
    assert (await r.run_command('echo "unterminated', str(tmp_path))).error.startswith("cannot parse")
    assert (await r.run_command("   ", str(tmp_path))).error == "empty command"


async def test_no_commands_is_failure(tmp_path: Path):
    rep = await VerificationRunner().verify(str(tmp_path))
    assert not rep.passed and "no verification suite" in rep.reason


async def test_env_is_passed(tmp_path: Path):
    cmd = f'{sys.executable} -c "import os,sys; sys.exit(0 if os.environ.get(\'X\')==\'1\' and os.environ[\'CI\']==\'1\' else 1)"'
    assert (await VerificationRunner().verify(str(tmp_path), [cmd], env={"X": "1"})).passed


def test_report_digest_truncation_and_empty():
    big = CommandResult(command="c", exit_code=1, stdout="o" * 50_000, stderr="e" * 50_000)
    d = VerificationReport.from_results([big]).failure_digest(max_chars=2000)
    assert len(d) <= 2100 and "truncated" in d
    assert not VerificationReport.from_results([]).passed
    assert VerificationReport.from_results([CommandResult(command="c", exit_code=0)]).failure_digest() == "All verification checks passed."


# --------------------------------------------------------------------------- verify.json contract
import socket  # noqa: E402

from verification import load_contract  # noqa: E402


def write_contract(ws: Path, data) -> None:
    (ws / ".orchestrator").mkdir(exist_ok=True)
    (ws / ".orchestrator" / "verify.json").write_text(data if isinstance(data, str) else json.dumps(data))


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def test_contract_full_flow(tmp_path: Path):
    (tmp_path / "test_a.py").write_text("def test_ok():\n    assert True\n")
    py = sys.executable
    port = free_port()
    write_contract(tmp_path, {
        "setup": [f'{py} -c "open(\'setup.done\',\'w\').write(\'1\')"'],
        "test": f"{py} -m pytest -q",
        "build": [f"{py} -m py_compile test_a.py"],
        "smoke": [f'{py} -c "print(42)"',
                  {"command": f"{py} -m http.server {port} --bind 127.0.0.1", "url": f"http://127.0.0.1:{port}/", "timeout_s": 20}],
    })
    rep = await VerificationRunner().verify(str(tmp_path))
    assert rep.passed, rep.failure_digest()
    assert [r.kind for r in rep.results] == ["setup", "build", "test", "smoke", "smoke"]
    assert (tmp_path / "setup.done").exists()
    with socket.socket() as s:  # the smoke server was shut down
        assert s.connect_ex(("127.0.0.1", port)) != 0


async def test_contract_rejects_noop_and_missing_tests(tmp_path: Path):
    write_contract(tmp_path, {"test": ["true", "echo ok"]})
    rep = await VerificationRunner().verify(str(tmp_path))
    assert not rep.passed and "no real test command" in rep.reason
    write_contract(tmp_path, {"build": ["make"]})
    assert "no real test command" in (await VerificationRunner().verify(str(tmp_path))).reason


async def test_contract_invalid_json(tmp_path: Path):
    write_contract(tmp_path, "{not json")
    rep = await VerificationRunner().verify(str(tmp_path))
    assert not rep.passed and "invalid" in rep.reason
    assert load_contract(tmp_path / "nowhere") == (None, None)


async def test_contract_setup_failure_stops(tmp_path: Path):
    write_contract(tmp_path, {"setup": [f'{sys.executable} -c "raise SystemExit(4)"'], "test": [f"{sys.executable} -m pytest"]})
    rep = await VerificationRunner().verify(str(tmp_path))
    assert not rep.passed and len(rep.results) == 1 and rep.reason == "setup command failed"


async def test_server_smoke_failures(tmp_path: Path):
    port = free_port()
    write_contract(tmp_path, {
        "test": [f'{sys.executable} -c "pass"'],
        "smoke": [{"command": f'{sys.executable} -c "raise SystemExit(3)"', "url": f"http://127.0.0.1:{port}/", "timeout_s": 5},
                  {"command": f'{sys.executable} -c "import time; time.sleep(60)"', "url": f"http://127.0.0.1:{port}/", "timeout_s": 1}],
    })
    rep = await VerificationRunner(kill_grace_s=0.5).verify(str(tmp_path))
    assert not rep.passed
    early, silent = rep.results[1], rep.results[2]
    assert "exited with code 3" in early.error
    assert "did not answer" in silent.error


async def test_explicit_commands_override_contract(tmp_path: Path):
    write_contract(tmp_path, {"test": ["true"]})
    rep = await VerificationRunner().verify(str(tmp_path), [f'{sys.executable} -c "pass"'])
    assert rep.passed
