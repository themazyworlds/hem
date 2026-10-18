"""
Hem • Compatibility layer for Hem 0.1.

Everything here is deprecated in favour of ``hem.Sandbox`` / ``hem.run`` but keeps working with zero breakage:
``BubblewrapBuilder`` (raw fluent bwrap builder), ``create_sandbox``, ``wrap_command``, ``run_sandboxed``,
``async_run_sandboxed``, ``run_command``, ``async_run_command``, ``apply_resources``, ``allows_network``, and
``requires_host_session``.

Behaviour improvements versus early 0.1 (all security fixes preserved):
- The launcher process is always started with a sanitized minimal environment (never leaking host secrets into /proc/1/environ).
- Resource matching is exact against ("net", "network").
- dbus:session binds the bus socket only, never the runtime directory.
- PID namespace isolation is preserved by default.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path
from subprocess import CompletedProcess
from typing import IO, Any, Self

from hem.backends.bwrap import BubblewrapBackend
from hem.errors import SandboxUnavailableError
from hem.runner import async_run_argv, popen_argv, run_argv


class BubblewrapBuilder:
    """Fluent, type-safe builder for constructing Bubblewrap (bwrap) execution arguments."""

    def __init__(
        self,
        bwrap_path: str | Path | None = None,
        *,
        require_available: bool = False,
    ) -> None:
        if require_available and not self.is_available():
            raise SandboxUnavailableError()
        resolved_bwrap = str(bwrap_path) if bwrap_path else (shutil.which("bwrap") or "bwrap")
        self._args: list[str] = [resolved_bwrap]

    def ensure_available(self) -> Self:
        """Verify bubblewrap is operational on the host system, raising SandboxUnavailableError if not."""
        if not self.is_available():
            raise SandboxUnavailableError()
        return self

    @classmethod
    def is_available(cls) -> bool:
        """Check if bubblewrap (bwrap) executable is present and working on the host."""
        return BubblewrapBackend().is_available()

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
        """Bind host character or block device node inside container."""
        src_str = str(src)
        dest_str = str(dest) if dest is not None else src_str
        flag = "--dev-bind-try" if try_ok else "--dev-bind"
        self._args.extend([flag, src_str, dest_str])
        return self

    def tmpfs(self, path: str | Path, *, size: int | None = None, perms: int | None = None) -> Self:
        """Mount tmpfs instance inside container."""
        self._args.extend(["--tmpfs", str(path)])
        if size is not None:
            self._args.extend(["--size", str(size)])
        if perms is not None:
            self._args.extend(["--perms", oct(perms)[2:]])
        return self

    def dev(self, path: str | Path = "/dev") -> Self:
        """Mount minimal standard devtmpfs inside container."""
        self._args.extend(["--dev", str(path)])
        return self

    def proc(self, path: str | Path = "/proc") -> Self:
        """Mount new procfs inside container."""
        self._args.extend(["--proc", str(path)])
        return self

    def symlink(self, target: str | Path, link_name: str | Path) -> Self:
        """Create a symlink pointing to target at link_name inside container."""
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
        """Unshare all available namespaces."""
        self._args.append("--unshare-all")
        return self

    def unshare(self, *namespaces: str) -> Self:
        """Selectively unshare specific Linux kernel namespaces."""
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

    def set_namespaces(
        self,
        allow_network: bool = False,
        unshare_user: bool = True,
        unshare_pid: bool = True,
    ) -> Self:
        """Configure standard execution namespaces with deterministic parent termination."""
        ns: list[str] = ["ipc", "uts"]
        if unshare_user:
            ns.append("user")
        if unshare_pid:
            ns.append("pid")
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

    def bind_python_runtime(self, extra_paths: Sequence[str | Path] | None = None) -> Self:
        """Bind Python virtualenv prefixes, sys.path locations, and extra package paths into sandbox."""
        for check_path in (sys.prefix, sys.base_prefix, getattr(sys, "base_exec_prefix", None)):
            if check_path and Path(check_path).exists():
                p_resolved = Path(check_path).resolve()
                p_str = str(p_resolved)
                if not any(p_str.startswith(prefix) for prefix in ("/usr", "/lib", "/opt", "/nix")):
                    self.ro_bind(p_resolved, try_ok=True)

        sys_temp = tempfile.gettempdir()
        ignored_prefixes = ("/usr", "/lib", "/opt", "/nix", sys_temp)
        for entry in sys.path:
            if entry and Path(entry).exists():
                p_res = Path(entry).resolve()
                p_str = str(p_res)
                if not any(p_str.startswith(prefix) for prefix in ignored_prefixes):
                    target = p_res.parent if p_res.name == "src" else p_res
                    self.ro_bind(target, try_ok=True)

        if extra_paths:
            for extra in extra_paths:
                if extra and Path(extra).exists():
                    self.ro_bind(Path(extra).resolve(), try_ok=True)

        return self

    def bind_executable_dependencies(self, cmd: Sequence[str]) -> Self:
        """Bind target executable path and containing venv or linked source directories into sandbox."""
        if not cmd or not cmd[0]:
            return self
        exe_target = shutil.which(cmd[0]) or cmd[0]
        if not Path(exe_target).exists():
            return self

        raw_path = str(Path(exe_target).absolute())
        resolved_path = str(Path(exe_target).resolve())
        for p_str in (raw_path, resolved_path):
            if ".venv" in p_str:
                venv_root = p_str.split("/bin/")[0]
                self.ro_bind(venv_root, try_ok=True)
                with contextlib.suppress(OSError):
                    for pth in Path(venv_root).glob("lib*/python*/site-packages/*.pth"):
                        for line in pth.read_text(encoding="utf-8").splitlines():
                            target_line = line.strip()
                            if target_line and not target_line.startswith(("#", "import ")):
                                p_pth = Path(target_line).resolve()
                                if p_pth.exists():
                                    bind_target = p_pth.parent if p_pth.name == "src" else p_pth
                                    self.ro_bind(bind_target, try_ok=True)
            if p_str.startswith(str(Path.home() / ".local")):
                self.ro_bind(Path.home() / ".local", try_ok=True)
            elif not any(p_str.startswith(prefix) for prefix in ("/usr", "/bin", "/lib", "/opt", "/nix")):
                p_path = Path(p_str)
                if p_path.parent.name == "bin":
                    self.ro_bind(p_path.parent.parent, try_ok=True)
                else:
                    self.ro_bind(p_path.parent, try_ok=True)

        return self

    def bind_script_sources(self, cmd: Sequence[str]) -> Self:
        """Inspect command arguments and bind any script files or existing directory trees."""
        for arg in cmd:
            if arg.endswith(".py") or Path(arg).exists():
                p_arg = Path(arg).resolve()
                if p_arg.is_file():
                    self.ro_bind(p_arg.parent, try_ok=True)
                elif p_arg.is_dir():
                    self.ro_bind(p_arg, try_ok=True)
        return self

    def set_standard_env(
        self,
        env: dict[str, str] | None = None,
        *,
        uv_cache_dir: str | Path | None = None,
    ) -> Self:
        """Configure standard container environment variables and mount PYTHONPATH directories."""
        target_env = env if env is not None else dict(os.environ)

        self.setenv("HOME", target_env.get("HOME", str(Path.home())))
        self.setenv("USER", target_env.get("USER", os.getenv("USER", "user")))
        self.setenv("PATH", target_env.get("PATH", "/usr/bin:/bin"))
        if uv_cache_dir:
            self.setenv("UV_CACHE_DIR", str(uv_cache_dir))
        else:
            self.setenv("UV_CACHE_DIR", target_env.get("UV_CACHE_DIR", "/tmp/uv_cache"))

        self.setenv("PYTHONPATH", target_env.get("PYTHONPATH"))
        self.setenv("TERMINAL", target_env.get("TERMINAL"))
        self.setenv("XDG_CONFIG_HOME", target_env.get("XDG_CONFIG_HOME"))
        self.setenv("XDG_DATA_HOME", target_env.get("XDG_DATA_HOME"))
        self.setenv("XDG_RUNTIME_DIR", target_env.get("XDG_RUNTIME_DIR"))

        pythonpath = target_env.get("PYTHONPATH") or ""
        if pythonpath:
            for p in pythonpath.split(":"):
                if p and Path(p).exists():
                    self.ro_bind(Path(p).resolve(), try_ok=True)

        return self

    def build(self, target_cmd: Sequence[str] | None = None) -> list[str]:
        """Compile complete Bubblewrap command tokens."""
        return list(self._args) + (list(target_cmd) if target_cmd else [])

    def run(
        self,
        target_cmd: Sequence[str] | None = None,
        *,
        require_available: bool = True,
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
    ) -> CompletedProcess[Any]:
        """Execute built container command synchronously using sanitized runner."""
        if require_available:
            self.ensure_available()
        full_cmd = self.build(target_cmd)
        return run_argv(
            full_cmd,
            capture_output=capture_output,
            check=check,
            timeout=timeout,
            cwd=cwd,
            env=env,
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
        require_available: bool = True,
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
    ) -> CompletedProcess[Any]:
        """Execute built container command asynchronously using sanitized runner."""
        if require_available:
            self.ensure_available()
        full_cmd = self.build(target_cmd)
        return await async_run_argv(
            full_cmd,
            capture_output=capture_output,
            check=check,
            timeout=timeout,
            cwd=cwd,
            env=env,
            text=text,
            input=input,
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
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
        """Spawn the built bubblewrap command with sanitized launcher environment."""
        full_cmd = self.build(target_cmd)
        return popen_argv(
            full_cmd,
            cwd=cwd,
            env=env,
            text=text,
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
        )


def run_command(
    cmd: Sequence[str],
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
) -> CompletedProcess[Any]:
    """Execute a command synchronously with sanitized launcher environment."""
    return run_argv(
        cmd,
        capture_output=capture_output,
        check=check,
        timeout=timeout,
        cwd=cwd,
        env=env,
        text=text,
        input=input,
        stdin=stdin,
        stdout=stdout,
        stderr=stderr,
    )


async def async_run_command(
    cmd: Sequence[str],
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
) -> CompletedProcess[Any]:
    """Execute a command asynchronously with sanitized launcher environment."""
    return await async_run_argv(
        cmd,
        capture_output=capture_output,
        check=check,
        timeout=timeout,
        cwd=cwd,
        env=env,
        text=text,
        input=input,
        stdin=stdin,
        stdout=stdout,
        stderr=stderr,
    )


_HOST_SESSION_SPECIFIERS = (
    "dbus:session",
    "dbus-session",
    "display",
    "display:wayland",
    "session",
)


def requires_host_session(resources: Sequence[str] | None) -> bool:
    """Check if granted resources require preserving host user namespace."""
    if not resources:
        return False
    return any(
        str(r).lower() in _HOST_SESSION_SPECIFIERS or str(r).lower().startswith("env:xdg_runtime_dir")
        for r in resources
    )


def allows_network(resources: Sequence[str] | None) -> bool:
    """Check if granted resources include network access permissions (exact token matching)."""
    if not resources:
        return False
    return any(str(r).lower().strip() in ("net", "network") for r in resources)


def apply_resources(builder: BubblewrapBuilder, resources: Sequence[str]) -> None:
    """Legacy helper: apply declarative resource specifiers directly to BubblewrapBuilder."""
    for res_name in resources:
        clean_res = res_name.strip()
        if not clean_res:
            continue
        lowered = clean_res.lower()
        if lowered in ("display", "display:wayland", "display:x11"):
            wayland_display = os.environ.get("WAYLAND_DISPLAY")
            runtime = os.environ.get("XDG_RUNTIME_DIR")
            if wayland_display and runtime:
                wl_sock = os.path.join(runtime, wayland_display)
                if Path(wl_sock).exists():
                    builder.ro_bind(wl_sock).setenv("WAYLAND_DISPLAY", wayland_display).setenv("XDG_RUNTIME_DIR", runtime)
            if x11_display := os.environ.get("DISPLAY"):
                builder.setenv("DISPLAY", x11_display)
                x11_sock = os.path.join("/", "tmp", ".X11-unix")
                if Path(x11_sock).exists():
                    builder.ro_bind(x11_sock)
        elif lowered in ("sound", "sound:pipewire", "sound:pulseaudio"):
            if runtime := os.environ.get("XDG_RUNTIME_DIR"):
                for sock_name in ("pipewire-0", "pulse"):
                    p = os.path.join(runtime, sock_name)
                    if Path(p).exists():
                        builder.ro_bind(p)
        elif lowered in ("dbus:session", "dbus-session"):
            runtime = os.environ.get("XDG_RUNTIME_DIR")
            if runtime:
                builder.setenv("XDG_RUNTIME_DIR", runtime)
            bus_addr = os.environ.get("DBUS_SESSION_BUS_ADDRESS")
            if bus_addr:
                builder.setenv("DBUS_SESSION_BUS_ADDRESS", bus_addr)
                if "unix:path=" in bus_addr:
                    sock_path = bus_addr.split("unix:path=")[1].split(",")[0]
                    if Path(sock_path).exists():
                        builder.ro_bind(sock_path)
            elif runtime:
                default_bus = os.path.join(runtime, "bus")
                if Path(default_bus).exists():
                    builder.ro_bind(default_bus).setenv("DBUS_SESSION_BUS_ADDRESS", f"unix:path={default_bus}")
        elif lowered in ("dbus:system", "dbus-system"):
            for sys_bus in ("/run/dbus/system_bus_socket", "/var/run/dbus/system_bus_socket"):
                if Path(sys_bus).exists():
                    builder.ro_bind(sys_bus)
                    break
        elif lowered in ("net", "network"):
            pass
        elif lowered.startswith("socket:"):
            expanded = os.path.expandvars(os.path.expanduser(clean_res[7:].strip()))
            sock_p = Path(expanded)
            if sock_p.exists():
                builder.ro_bind(sock_p)
            elif sock_p.parent.exists():
                builder.ro_bind(sock_p.parent, try_ok=True)
        elif lowered.startswith("env:"):
            env_spec = clean_res[4:].strip()
            if "=" in env_spec:
                k, v = env_spec.split("=", 1)
                builder.setenv(k, v)
            elif val := os.environ.get(env_spec):
                builder.setenv(env_spec, val)


def create_sandbox(
    cmd: Sequence[str],
    *,
    workspace: str | Path | None = None,
    writable: bool = False,
    resources: Sequence[str] | None = None,
    env: dict[str, str] | None = None,
    extra_ro_binds: Sequence[str | Path] | None = None,
    extra_binds: Sequence[str | Path] | None = None,
    allow_network: bool | None = None,
) -> BubblewrapBuilder:
    """Create and configure a BubblewrapBuilder sandbox container for cmd (legacy API)."""
    ws = Path(workspace or Path.cwd()).resolve()
    net = allow_network if allow_network is not None else allows_network(resources)
    host_session = requires_host_session(resources)

    container_tmp = os.path.join("/", "tmp")
    container_home = os.path.join("/", "home")

    builder = (
        BubblewrapBuilder()
        .clearenv()
        .bind_system_base()
        .bind_tmpfs_paths([container_tmp, container_home])
        .set_namespaces(allow_network=net, unshare_user=not host_session, unshare_pid=True)
        .bind_workspace(ws, writable=writable)
        .set_standard_env(env)
        .bind_python_runtime()
        .bind_executable_dependencies(cmd)
        .bind_script_sources(cmd)
    )

    if extra_ro_binds:
        for p in extra_ro_binds:
            p_obj = Path(p).resolve()
            if p_obj.exists():
                builder.ro_bind(p_obj, try_ok=True)

    if extra_binds:
        for p in extra_binds:
            p_obj = Path(p).resolve()
            if p_obj.exists():
                builder.bind(p_obj, try_ok=True)

    if resources:
        apply_resources(builder, resources)

    return builder


def wrap_command(
    cmd: Sequence[str],
    *,
    workspace: str | Path | None = None,
    writable: bool = False,
    resources: Sequence[str] | None = None,
    env: dict[str, str] | None = None,
    extra_ro_binds: Sequence[str | Path] | None = None,
    extra_binds: Sequence[str | Path] | None = None,
    allow_network: bool | None = None,
) -> list[str]:
    """Wrap command in a bwrap sandbox container argument list (legacy API)."""
    builder = create_sandbox(
        cmd,
        workspace=workspace,
        writable=writable,
        resources=resources,
        env=env,
        extra_ro_binds=extra_ro_binds,
        extra_binds=extra_binds,
        allow_network=allow_network,
    )
    return builder.build(cmd)


def run_sandboxed(
    cmd: Sequence[str],
    *,
    workspace: str | Path | None = None,
    writable: bool = False,
    resources: Sequence[str] | None = None,
    env: dict[str, str] | None = None,
    extra_ro_binds: Sequence[str | Path] | None = None,
    extra_binds: Sequence[str | Path] | None = None,
    allow_network: bool | None = None,
    capture_output: bool = False,
    check: bool = False,
    timeout: float | None = None,
    text: bool = False,
) -> CompletedProcess[Any]:
    """Execute command in a sandboxed container synchronously (legacy API)."""
    builder = create_sandbox(
        cmd,
        workspace=workspace,
        writable=writable,
        resources=resources,
        env=env,
        extra_ro_binds=extra_ro_binds,
        extra_binds=extra_binds,
        allow_network=allow_network,
    )
    return builder.run(
        cmd,
        capture_output=capture_output,
        check=check,
        timeout=timeout,
        text=text,
        env=env,
    )


async def async_run_sandboxed(
    cmd: Sequence[str],
    *,
    workspace: str | Path | None = None,
    writable: bool = False,
    resources: Sequence[str] | None = None,
    env: dict[str, str] | None = None,
    extra_ro_binds: Sequence[str | Path] | None = None,
    extra_binds: Sequence[str | Path] | None = None,
    allow_network: bool | None = None,
    capture_output: bool = False,
    check: bool = False,
    timeout: float | None = None,
    text: bool = False,
) -> CompletedProcess[Any]:
    """Execute command in a sandboxed container asynchronously (legacy API)."""
    builder = create_sandbox(
        cmd,
        workspace=workspace,
        writable=writable,
        resources=resources,
        env=env,
        extra_ro_binds=extra_ro_binds,
        extra_binds=extra_binds,
        allow_network=allow_network,
    )
    return await builder.async_run(
        cmd,
        capture_output=capture_output,
        check=check,
        timeout=timeout,
        text=text,
        env=env,
    )
