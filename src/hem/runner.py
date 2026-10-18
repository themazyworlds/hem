"""
Hem • Process Lifecycle & Subprocess Runner.
Spawns sandbox containers with sanitized launcher environments, process group isolation, and deterministic termination.
"""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from subprocess import CalledProcessError, CompletedProcess, TimeoutExpired
from typing import IO, Any

_STANDARD_LAUNCHER_ENV_KEYS: tuple[str, ...] = (
    "PATH",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "TERM",
    "USER",
    "LOGNAME",
    "HOME",
    "SHELL",
    "TMPDIR",
    "XDG_RUNTIME_DIR",
)


def get_minimal_env(base_env: Mapping[str, str] | None = None) -> dict[str, str]:
    """
    Construct a sanitized, minimal host execution environment.
    Guarantees host credentials and arbitrary secrets never leak into bwrap's process environment (/proc/1/environ).
    """
    src = dict(os.environ) if base_env is None else dict(base_env)
    minimal: dict[str, str] = {}
    for k in _STANDARD_LAUNCHER_ENV_KEYS:
        if k in src:
            minimal[k] = src[k]

    if "PATH" not in minimal:
        minimal["PATH"] = "/usr/bin:/bin"

    return minimal


def _kill_process_group(pid: int) -> None:
    """Send SIGKILL to the entire process group of the target process."""
    try:
        pgid = os.getpgid(pid)
        os.killpg(pgid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
            os.kill(pid, signal.SIGKILL)


import contextlib


def popen_argv(
    cmd: Sequence[str],
    *,
    env: Mapping[str, str] | None = None,
    cwd: str | Path | None = None,
    text: bool = False,
    stdin: int | IO[Any] | None = None,
    stdout: int | IO[Any] | None = None,
    stderr: int | IO[Any] | None = None,
) -> subprocess.Popen[Any]:
    """Spawn sandbox process with sanitized launcher environment."""
    launcher_env = get_minimal_env(env)
    return subprocess.Popen(
        list(cmd),
        cwd=cwd,
        env=launcher_env,
        text=text,
        stdin=stdin,
        stdout=stdout,
        stderr=stderr,
        start_new_session=True,
    )


def run_argv(
    cmd: Sequence[str],
    *,
    env: Mapping[str, str] | None = None,
    cwd: str | Path | None = None,
    timeout: float | None = None,
    capture_output: bool = False,
    check: bool = False,
    text: bool = False,
    input: str | bytes | None = None,
    stdin: int | IO[Any] | None = None,
    stdout: int | IO[Any] | None = None,
    stderr: int | IO[Any] | None = None,
) -> CompletedProcess[Any]:
    """
    Execute a sandboxed command synchronously with process-group cleanup on timeout.
    """
    launcher_env = get_minimal_env(env)

    target_stdout = subprocess.PIPE if capture_output else stdout
    target_stderr = subprocess.PIPE if capture_output else stderr
    target_stdin = subprocess.PIPE if input is not None else stdin

    proc = subprocess.Popen(
        list(cmd),
        cwd=cwd,
        env=launcher_env,
        text=text,
        stdin=target_stdin,
        stdout=target_stdout,
        stderr=target_stderr,
        start_new_session=True,
    )

    try:
        out, err = proc.communicate(input=input, timeout=timeout)
    except TimeoutExpired as exc:
        _kill_process_group(proc.pid)
        proc.wait()
        raise TimeoutExpired(cmd, timeout or 0.0, output=getattr(exc, "output", None), stderr=getattr(exc, "stderr", None)) from None
    except Exception:
        _kill_process_group(proc.pid)
        proc.wait()
        raise

    retcode = proc.poll() or 0
    res = CompletedProcess(
        args=list(cmd),
        returncode=retcode,
        stdout=out if capture_output else None,
        stderr=err if capture_output else None,
    )

    if check and retcode != 0:
        raise CalledProcessError(retcode, list(cmd), output=out, stderr=err)

    return res


async def async_run_argv(
    cmd: Sequence[str],
    *,
    env: Mapping[str, str] | None = None,
    cwd: str | Path | None = None,
    timeout: float | None = None,
    capture_output: bool = False,
    check: bool = False,
    text: bool = False,
    input: str | bytes | None = None,
    stdin: int | None = None,
    stdout: int | None = None,
    stderr: int | None = None,
) -> CompletedProcess[Any]:
    """
    Execute a sandboxed command asynchronously with process-group cleanup on timeout.
    """
    launcher_env = get_minimal_env(env)
    target_cwd = str(cwd) if cwd is not None else None

    proc_stdout = asyncio.subprocess.PIPE if capture_output else stdout
    proc_stderr = asyncio.subprocess.PIPE if capture_output else stderr
    proc_stdin = asyncio.subprocess.PIPE if input is not None else stdin

    input_bytes: bytes | None = None
    if input is not None:
        input_bytes = input.encode("utf-8") if isinstance(input, str) else input

    proc = await asyncio.create_subprocess_exec(
        *list(cmd),
        cwd=target_cwd,
        env=launcher_env,
        stdin=proc_stdin,
        stdout=proc_stdout,
        stderr=proc_stderr,
        start_new_session=True,
    )

    try:
        if timeout is not None and timeout > 0:
            out_bytes, err_bytes = await asyncio.wait_for(
                proc.communicate(input=input_bytes),
                timeout=timeout,
            )
        else:
            out_bytes, err_bytes = await proc.communicate(input=input_bytes)
    except TimeoutError:
        _kill_process_group(proc.pid)
        await proc.wait()
        raise TimeoutExpired(cmd, timeout or 0.0) from None
    except Exception:
        _kill_process_group(proc.pid)
        await proc.wait()
        raise

    retcode = proc.returncode if proc.returncode is not None else 0
    final_out: Any = out_bytes
    final_err: Any = err_bytes
    if text:
        if out_bytes is not None:
            final_out = out_bytes.decode("utf-8", errors="replace")
        if err_bytes is not None:
            final_err = err_bytes.decode("utf-8", errors="replace")

    res = CompletedProcess(
        args=list(cmd),
        returncode=retcode,
        stdout=final_out if capture_output else None,
        stderr=final_err if capture_output else None,
    )

    if check and retcode != 0:
        raise CalledProcessError(retcode, list(cmd), output=final_out, stderr=final_err)

    return res
