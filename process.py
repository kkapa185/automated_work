"""Async subprocess execution with streaming, timeouts and process-group cleanup."""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import time
from dataclasses import dataclass
from typing import Callable, Mapping, Sequence

LineCallback = Callable[[str, str], None]  # (stream_name, line)

READ_CHUNK = 64 * 1024


@dataclass
class ProcessResult:
    argv: list[str]
    exit_code: int | None
    stdout: str
    stderr: str
    duration_s: float
    timed_out: bool = False
    pid: int | None = None


def _signal_group(proc: asyncio.subprocess.Process, sig: int) -> None:
    if proc.returncode is not None:
        return
    try:
        os.killpg(proc.pid, sig)
    except (ProcessLookupError, PermissionError):
        with contextlib.suppress(ProcessLookupError):
            proc.send_signal(sig)


async def terminate_process(proc: asyncio.subprocess.Process, grace_s: float = 5.0) -> None:
    """SIGTERM the whole process group, escalate to SIGKILL, and always reap the child."""
    if proc.returncode is None:
        _signal_group(proc, signal.SIGTERM)
        try:
            await asyncio.wait_for(proc.wait(), timeout=grace_s)
        except asyncio.TimeoutError:
            _signal_group(proc, signal.SIGKILL)
    # Kill any orphaned grandchildren still in the group, then reap.
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(proc.pid, signal.SIGKILL)
    with contextlib.suppress(ProcessLookupError):
        await proc.wait()


async def _pump(stream: asyncio.StreamReader, name: str, sink: list[str], cb: LineCallback | None) -> None:
    pending = ""
    while True:
        chunk = await stream.read(READ_CHUNK)
        if not chunk:
            break
        text = chunk.decode("utf-8", errors="replace")
        sink.append(text)
        if cb is not None:
            pending += text
            *lines, pending = pending.split("\n")
            for line in lines:
                with contextlib.suppress(Exception):
                    cb(name, line)
    if cb is not None and pending:
        with contextlib.suppress(Exception):
            cb(name, pending)


async def run_process(
    argv: Sequence[str],
    *,
    cwd: str | os.PathLike[str] | None = None,
    env: Mapping[str, str] | None = None,
    timeout_s: float | None = None,
    stdin_data: bytes | None = None,
    on_line: LineCallback | None = None,
    kill_grace_s: float = 5.0,
) -> ProcessResult:
    """Run ``argv`` (no shell) in its own process group, streaming output to ``on_line``.

    On timeout the process group is terminated and ``timed_out`` is set. On task
    cancellation the group is terminated and ``CancelledError`` propagates. The child
    is always reaped, so no zombies are left behind. ``FileNotFoundError`` propagates
    when the executable does not exist.
    """
    start = time.monotonic()
    proc = await asyncio.create_subprocess_exec(
        *argv,
        cwd=str(cwd) if cwd is not None else None,
        env=dict(env) if env is not None else None,
        stdin=asyncio.subprocess.PIPE if stdin_data is not None else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    out: list[str] = []
    err: list[str] = []
    assert proc.stdout is not None and proc.stderr is not None

    async def feed() -> None:
        if stdin_data is not None and proc.stdin is not None:
            with contextlib.suppress(BrokenPipeError, ConnectionResetError):
                proc.stdin.write(stdin_data)
                await proc.stdin.drain()
            proc.stdin.close()

    async def body() -> int:
        await asyncio.gather(feed(), _pump(proc.stdout, "stdout", out, on_line), _pump(proc.stderr, "stderr", err, on_line))
        return await proc.wait()

    timed_out = False
    exit_code: int | None
    work = asyncio.ensure_future(body())
    try:
        exit_code = await asyncio.wait_for(asyncio.shield(work), timeout=timeout_s)
    except asyncio.TimeoutError:
        timed_out = True
        await terminate_process(proc, kill_grace_s)
        with contextlib.suppress(asyncio.TimeoutError, asyncio.CancelledError):
            await asyncio.wait_for(work, timeout=kill_grace_s)
        if not work.done():
            work.cancel()
        exit_code = proc.returncode
    except asyncio.CancelledError:
        await terminate_process(proc, kill_grace_s)
        work.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await work
        raise
    return ProcessResult(
        argv=list(argv),
        exit_code=exit_code,
        stdout="".join(out),
        stderr="".join(err),
        duration_s=time.monotonic() - start,
        timed_out=timed_out,
        pid=proc.pid,
    )
