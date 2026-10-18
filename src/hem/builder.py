"""
Hem • Bubblewrap (bwrap) Command Builder.
Pure-Python, type-safe, fluent builder for Linux unprivileged container execution arguments.
Zero runtime dependencies.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import IO, Any, Self


class BubblewrapBuilder:
    """Fluent, type-safe builder for constructing Bubblewrap (bwrap) execution arguments."""

    _AVAILABLE: bool | None = None

    def __init__(self, bwrap_path: str | Path | None = None) -> None:
        resolved_bwrap = str(bwrap_path) if bwrap_path else (shutil.which("bwrap") or "bwrap")
        self._args: list[str] = [resolved_bwrap]

    @classmethod
    def is_available(cls) -> bool:
        """Check if bubblewrap (bwrap) executable is present and working on the host."""
        if cls._AVAILABLE is not None:
            return cls._AVAILABLE
        if sys.platform != "linux":
            cls._AVAILABLE = False
            return False
        bwrap_path = shutil.which("bwrap")
        if not bwrap_path:
            cls._AVAILABLE = False
            return False
        try:
            res = subprocess.run(
                [bwrap_path, "--version"],
                capture_output=True,
                text=True,
                timeout=2.0,
                check=False,
            )
            cls._AVAILABLE = res.returncode == 0
            return cls._AVAILABLE
        except (OSError, subprocess.SubprocessError):
            cls._AVAILABLE = False
            return False

    @property
    def args(self) -> list[str]:
        """Return a copy of the current list of CLI argument tokens."""
        return list(self._args)

    def copy(self) -> BubblewrapBuilder:
        """Create an independent copy of this builder for branching configuration."""
        cloned = BubblewrapBuilder(self._args[0])
        cloned._args = list(self._args)
        return cloned

    def clearenv(self) -> Self:
        """Unset all environment variables inside container."""
        self._args.append("--clearenv")
        return self

    def setenv(self, key: str, value: str | None) -> Self:
        """Set environment variable inside container."""
        if value is not None:
            self._args.extend(["--setenv", str(key), str(value)])
        return self

    def unsetenv(self, key: str) -> Self:
        """Unset specified environment variable inside container."""
        self._args.extend(["--unsetenv", str(key)])
        return self

    def ro_bind(self, src: str | Path, dest: str | Path | None = None, *, try_ok: bool = False) -> Self:
        """Bind source directory or file as read-only inside the container."""
        src_str = str(src)
        dest_str = str(dest) if dest is not None else src_str
        flag = "--ro-bind-try" if try_ok else "--ro-bind"
        self._args.extend([flag, src_str, dest_str])
        return self

    def bind(self, src: str | Path, dest: str | Path | None = None, *, try_ok: bool = False) -> Self:
        """Bind source directory or file as read-write inside the container."""
        src_str = str(src)
        dest_str = str(dest) if dest is not None else src_str
        flag = "--bind-try" if try_ok else "--bind"
        self._args.extend([flag, src_str, dest_str])
        return self

    def dev_bind(self, src: str | Path, dest: str | Path | None = None, *, try_ok: bool = False) -> Self:
        """Bind source device node inside the container."""
        src_str = str(src)
        dest_str = str(dest) if dest is not None else src_str
        flag = "--dev-bind-try" if try_ok else "--dev-bind"
        self._args.extend([flag, src_str, dest_str])
        return self

    def tmpfs(self, dest: str | Path) -> Self:
        """Mount a clean tmpfs filesystem at the destination path."""
        self._args.extend(["--tmpfs", str(dest)])
        return self

    def dev(self, dest: str | Path = "/dev") -> Self:
        """Mount a minimal /dev filesystem containing standard device nodes."""
        self._args.extend(["--dev", str(dest)])
        return self

    def proc(self, dest: str | Path = "/proc") -> Self:
        """Mount a clean /proc filesystem at destination."""
        self._args.extend(["--proc", str(dest)])
        return self

    def symlink(self, target: str | Path, link_name: str | Path) -> Self:
        """Create a symbolic link inside the container filesystem."""
        self._args.extend(["--symlink", str(target), str(link_name)])
        return self

    def dir(self, path: str | Path) -> Self:
        """Create a directory inside the container."""
        self._args.extend(["--dir", str(path)])
        return self

    def chdir(self, path: str | Path) -> Self:
        """Set working directory inside the container."""
        self._args.extend(["--chdir", str(path)])
        return self

    def die_with_parent(self, enabled: bool = True) -> Self:
        """Ensure the container process terminates automatically if calling process exits."""
        if enabled:
            self._args.append("--die-with-parent")
        return self

    def unshare_all(self) -> Self:
        """Unshare all available namespaces (user, pid, net, ipc, uts, cgroup)."""
        self._args.append("--unshare-all")
        return self

    def unshare(self, *namespaces: str) -> Self:
        """Selectively unshare specific Linux kernel namespaces (e.g. 'user', 'pid', 'net', 'ipc', 'uts', 'cgroup')."""
        for ns in namespaces:
            clean_ns = ns.strip().lstrip("-").replace("_", "-")
            if not clean_ns.startswith("unshare-"):
                clean_ns = f"unshare-{clean_ns}"
            self._args.append(f"--{clean_ns}")
        return self

    def share_net(self) -> Self:
        """Retain host network access even when unsharing namespaces."""
        self._args.append("--share-net")
        return self

    # High-level standard system assembly methods
    def bind_system_base(self) -> Self:
        """Mount system binaries, libraries, standard symlinks, and minimal dev/proc."""
        self.ro_bind("/usr")
        lib64_target = "usr/lib64" if Path("/usr/lib64").exists() else "usr/lib"
        self.symlink(lib64_target, "/lib64")
        self.symlink("usr/lib", "/lib")
        self.symlink("usr/bin", "/bin")
        self.symlink("usr/bin", "/sbin")

        for sys_dir in ("/etc", "/sys", "/opt", "/nix"):
            self.ro_bind(sys_dir, try_ok=True)

        self.dev("/dev").proc("/proc")
        return self

    def bind_tmpfs_paths(self, paths: Sequence[str | Path]) -> Self:
        """Mount empty tmpfs at multiple paths."""
        for p in paths:
            self.tmpfs(p)
        return self

    def set_namespaces(self, allow_network: bool = False, unshare_user: bool = True) -> Self:
        """Configure standard execution namespaces with deterministic parent termination."""
        ns: list[str] = ["ipc", "uts"]
        if unshare_user:
            ns.extend(["user", "pid"])
        if not allow_network:
            ns.append("net")
        self.unshare(*ns)
        self.die_with_parent()
        return self

    def bind_workspace(self, workspace: str | Path, writable: bool = False) -> Self:
        """Bind workspace directory and set as container working directory."""
        ws_path = Path(workspace).resolve()
        if writable:
            self.bind(ws_path)
        else:
            self.ro_bind(ws_path)
        self.chdir(ws_path)
        return self

    def build(self, target_cmd: Sequence[str] | None = None) -> list[str]:
        """Compile the complete Bubblewrap command tokens, appending target executable command."""
        return list(self._args) + (list(target_cmd) if target_cmd else [])

    def run(
        self,
        target_cmd: Sequence[str] | None = None,
        *,
        capture_output: bool = False,
        check: bool = False,
        timeout: float | None = None,
        cwd: str | Path | None = None,
        env: dict[str, str] | None = None,
        text: bool = False,
        input: str | bytes | None = None,
        stdin: int | IO[Any] | None = None,
        stdout: int | IO[Any] | None = None,
        stderr: int | IO[Any] | None = None,
    ) -> subprocess.CompletedProcess[Any]:
        """Execute the built bubblewrap command using subprocess.run."""
        full_cmd = self.build(target_cmd)
        target_env = os.environ.copy() if env is None else env
        return subprocess.run(
            full_cmd,
            capture_output=capture_output,
            check=check,
            timeout=timeout,
            cwd=cwd,
            env=target_env,
            text=text,
            input=input,
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
        )

    async def async_run(
        self,
        target_cmd: Sequence[str] | None = None,
        *,
        capture_output: bool = False,
        check: bool = False,
        timeout: float | None = None,
        cwd: str | Path | None = None,
        env: dict[str, str] | None = None,
        text: bool = False,
        input: str | bytes | None = None,
        stdin: int | None = None,
        stdout: int | None = None,
        stderr: int | None = None,
    ) -> subprocess.CompletedProcess[Any]:
        """Execute the built bubblewrap command asynchronously using asyncio.create_subprocess_exec."""
        full_cmd = self.build(target_cmd)
        target_env = os.environ.copy() if env is None else env
        target_cwd = str(cwd) if cwd is not None else None

        proc_stdout = stdout
        proc_stderr = stderr
        proc_stdin = stdin

        if capture_output:
            proc_stdout = asyncio.subprocess.PIPE
            proc_stderr = asyncio.subprocess.PIPE

        input_bytes: bytes | None = None
        if input is not None:
            proc_stdin = asyncio.subprocess.PIPE
            input_bytes = input.encode("utf-8") if isinstance(input, str) else input

        proc = await asyncio.create_subprocess_exec(
            *full_cmd,
            stdin=proc_stdin,
            stdout=proc_stdout,
            stderr=proc_stderr,
            cwd=target_cwd,
            env=target_env,
        )

        out_b: bytes | None = None
        err_b: bytes | None = None

        try:
            if timeout is not None and timeout > 0:
                out_b, err_b = await asyncio.wait_for(
                    proc.communicate(input=input_bytes),
                    timeout=timeout,
                )
            else:
                out_b, err_b = await proc.communicate(input=input_bytes)
        except TimeoutError:
            try:
                proc.kill()
            except (ProcessLookupError, OSError):
                pass
            await proc.wait()
            raise subprocess.TimeoutExpired(
                cmd=full_cmd,
                timeout=timeout or 0.0,
                output=out_b.decode("utf-8", errors="replace") if (text and out_b) else out_b,
                stderr=err_b.decode("utf-8", errors="replace") if (text and err_b) else err_b,
            ) from None
        except asyncio.CancelledError:
            try:
                proc.kill()
            except (ProcessLookupError, OSError):
                pass
            await proc.wait()
            raise

        out: Any = out_b
        err: Any = err_b
        if text:
            out = out_b.decode("utf-8", errors="replace") if out_b is not None else ""
            err = err_b.decode("utf-8", errors="replace") if err_b is not None else ""

        retcode = proc.returncode if proc.returncode is not None else 0
        if check and retcode != 0:
            raise subprocess.CalledProcessError(
                retcode,
                full_cmd,
                output=out,
                stderr=err,
            )

        return subprocess.CompletedProcess(
            args=full_cmd,
            returncode=retcode,
            stdout=out,
            stderr=err,
        )

    def popen(
        self,
        target_cmd: Sequence[str] | None = None,
        *,
        cwd: str | Path | None = None,
        env: dict[str, str] | None = None,
        text: bool = False,
        stdin: int | IO[Any] | None = None,
        stdout: int | IO[Any] | None = None,
        stderr: int | IO[Any] | None = None,
    ) -> subprocess.Popen[Any]:
        """Spawn the built bubblewrap command using subprocess.Popen."""
        full_cmd = self.build(target_cmd)
        target_env = os.environ.copy() if env is None else env
        return subprocess.Popen(
            full_cmd,
            cwd=cwd,
            env=target_env,
            text=text,
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
        )
