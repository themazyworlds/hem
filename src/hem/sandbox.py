"""
Hem • High-Level Sandbox API.
Production-grade, type-safe sandbox abstraction for containerizing processes.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path
from subprocess import CompletedProcess
from typing import IO, Any

from hem.builder import (
    BubblewrapBuilder,
)
from hem.resources import allows_network, apply_resources, requires_host_session


def is_available() -> bool:
    """Check if bubblewrap (bwrap) executable is present and working on the host."""
    return BubblewrapBuilder.is_available()


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
    """Create and configure a BubblewrapBuilder sandbox container for cmd."""
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
        .set_namespaces(allow_network=net, unshare_user=not host_session)
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
    """Wrap command in a bwrap sandbox container argument list."""
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
    extra_ro_binds: Sequence[str | Path] | None = None,
    extra_binds: Sequence[str | Path] | None = None,
    allow_network: bool | None = None,
    capture_output: bool = False,
    stdin: IO[Any] | int | None = None,
    stdout: IO[Any] | int | None = None,
    stderr: IO[Any] | int | None = None,
    timeout: float | None = None,
    check: bool = False,
    text: bool = False,
    env: dict[str, str] | None = None,
) -> CompletedProcess[str]:
    """Execute a command synchronously inside an isolated Bubblewrap sandbox."""
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
        stdin=stdin,
        stdout=stdout,
        stderr=stderr,
        timeout=timeout,
        check=check,
        text=text,
        env=env,
    )


async def async_run_sandboxed(
    cmd: Sequence[str],
    *,
    workspace: str | Path | None = None,
    writable: bool = False,
    resources: Sequence[str] | None = None,
    extra_ro_binds: Sequence[str | Path] | None = None,
    extra_binds: Sequence[str | Path] | None = None,
    allow_network: bool | None = None,
    capture_output: bool = False,
    stdin: int | None = None,
    stdout: int | None = None,
    stderr: int | None = None,
    timeout: float | None = None,
    check: bool = False,
    text: bool = False,
    env: dict[str, str] | None = None,
) -> CompletedProcess[str]:
    """Execute a command asynchronously inside an isolated Bubblewrap sandbox."""
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
        stdin=stdin,
        stdout=stdout,
        stderr=stderr,
        timeout=timeout,
        check=check,
        text=text,
        env=env,
    )


class Sandbox:
    """
    High-level Bubblewrap sandbox manager.
    Encapsulates workspace confinement, Linux namespaces, and host resource bridging.
    """

    is_available = staticmethod(is_available)

    def __init__(
        self,
        workspace: str | Path | None = None,
        *,
        writable: bool = False,
        resources: Sequence[str] | None = None,
        env: dict[str, str] | None = None,
        extra_ro_binds: Sequence[str | Path] | None = None,
        extra_binds: Sequence[str | Path] | None = None,
        allow_network: bool | None = None,
    ) -> None:
        self.workspace = workspace
        self.writable = writable
        self.resources = list(resources) if resources else None
        self.env = env
        self.extra_ro_binds = list(extra_ro_binds) if extra_ro_binds else None
        self.extra_binds = list(extra_binds) if extra_binds else None
        self.allow_network = allow_network

    def create_builder(self, cmd: Sequence[str]) -> BubblewrapBuilder:
        """Create and configure a BubblewrapBuilder sandbox container for cmd."""
        return create_sandbox(
            cmd,
            workspace=self.workspace,
            writable=self.writable,
            resources=self.resources,
            env=self.env,
            extra_ro_binds=self.extra_ro_binds,
            extra_binds=self.extra_binds,
            allow_network=self.allow_network,
        )

    def wrap_command(self, cmd: Sequence[str]) -> list[str]:
        """Wrap command in a bwrap sandbox container argument list."""
        return wrap_command(
            cmd,
            workspace=self.workspace,
            writable=self.writable,
            resources=self.resources,
            env=self.env,
            extra_ro_binds=self.extra_ro_binds,
            extra_binds=self.extra_binds,
            allow_network=self.allow_network,
        )

    def run(
        self,
        cmd: Sequence[str],
        *,
        capture_output: bool = False,
        stdin: IO[Any] | int | None = None,
        stdout: IO[Any] | int | None = None,
        stderr: IO[Any] | int | None = None,
        timeout: float | None = None,
        check: bool = False,
        text: bool = False,
        env: dict[str, str] | None = None,
    ) -> CompletedProcess[str]:
        """Execute command synchronously inside this sandbox."""
        return run_sandboxed(
            cmd,
            workspace=self.workspace,
            writable=self.writable,
            resources=self.resources,
            extra_ro_binds=self.extra_ro_binds,
            extra_binds=self.extra_binds,
            allow_network=self.allow_network,
            capture_output=capture_output,
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
            timeout=timeout,
            check=check,
            text=text,
            env=env or self.env,
        )

    async def async_run(
        self,
        cmd: Sequence[str],
        *,
        capture_output: bool = False,
        stdin: int | None = None,
        stdout: int | None = None,
        stderr: int | None = None,
        timeout: float | None = None,
        check: bool = False,
        text: bool = False,
        env: dict[str, str] | None = None,
    ) -> CompletedProcess[str]:
        """Execute command asynchronously inside this sandbox."""
        return await async_run_sandboxed(
            cmd,
            workspace=self.workspace,
            writable=self.writable,
            resources=self.resources,
            extra_ro_binds=self.extra_ro_binds,
            extra_binds=self.extra_binds,
            allow_network=self.allow_network,
            capture_output=capture_output,
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
            timeout=timeout,
            check=check,
            text=text,
            env=env or self.env,
        )
