"""
Hem • High-level API: ``hem.run``, ``hem.async_run``, ``hem.Sandbox``, ``Sandbox.explain``.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from subprocess import CompletedProcess
from typing import IO, Any

lazy from hem.backends.base import Backend
lazy from hem.backends.bwrap import BubblewrapBackend
lazy from hem.errors import SandboxUnavailableError
lazy from hem.profiles import Profile, ProfileContext, resolve_profile
lazy from hem.resources import Resource, parse_resources
lazy from hem.runner import async_run_argv, popen_argv, run_argv
lazy from hem.spec import SandboxSpec


def is_available() -> bool:
    """True when the default (bubblewrap) backend can enforce a sandbox on this host."""
    return BubblewrapBackend().is_available()


@dataclass(frozen=True, slots=True)
class Explanation:
    """A human-readable audit of what a sandbox exposes. Environment *values* are never included."""

    backend: str
    network: bool
    namespaces: dict[str, bool]
    mounts: tuple[tuple[str, str, str], ...]  # (mode, target, source)
    cwd: str | None
    env_keys: tuple[str, ...]

    def __str__(self) -> str:
        lines: list[str] = [
            f"backend      {self.backend}",
            f"network      {'allowed' if self.network else 'isolated'}",
        ]

        unshared = [name for name, is_unshared in self.namespaces.items() if is_unshared]
        lines.append(f"namespaces   unshared: {', '.join(unshared) if unshared else 'none'}")
        lines.append(f"cwd          {self.cwd or '(unspecified)'}")

        lines.append("filesystem")
        for mode, target, src in self.mounts:
            if mode == "symlink":
                lines.append(f"  symlink {target}  <- {src}")
            elif mode in ("tmpfs", "dev", "proc", "dir"):
                lines.append(f"  {mode:<6} {target}")
            else:
                lines.append(f"  {mode:<6} {target}")

        if self.env_keys:
            lines.append(f"environment  {', '.join(self.env_keys)}  (values hidden)")
        else:
            lines.append("environment  (none)")

        return "\n".join(lines)


@dataclass(frozen=True)
class Sandbox:
    """
    Immutable, branchable high-level sandbox configuration.
    """

    profile: str | Profile = "strict"
    backend: Backend = field(default_factory=BubblewrapBackend)
    workspace: Path | None = None
    writable: bool = False
    resources: tuple[Resource, ...] = field(default_factory=tuple)
    env: dict[str, str] = field(default_factory=lambda: dict(os.environ))
    unshare_user: bool = True

    def __init__(
        self,
        profile: str | Profile = "strict",
        *,
        backend: Backend | None = None,
        workspace: str | Path | None = None,
        writable: bool = False,
        resources: Iterable[str | Resource] | None = None,
        env: Mapping[str, str] | None = None,
        unshare_user: bool | None = None,
    ) -> None:
        parsed_res = parse_resources(resources)
        if unshare_user is None:
            from hem.compat import requires_host_session

            raw_tokens = [r if isinstance(r, str) else type(r).__name__.lower() for r in (resources or ())]
            unshare_user = not requires_host_session(raw_tokens)

        object.__setattr__(self, "profile", profile)
        object.__setattr__(self, "backend", backend or BubblewrapBackend())
        object.__setattr__(self, "workspace", Path(workspace).resolve() if workspace is not None else None)
        object.__setattr__(self, "writable", bool(writable))
        object.__setattr__(self, "resources", parsed_res)
        object.__setattr__(self, "env", dict(env) if env is not None else dict(os.environ))
        object.__setattr__(self, "unshare_user", unshare_user)

    def allow(self, *resources: str | Resource) -> Sandbox:
        """Return a new Sandbox with additional resource grants."""
        new_res = parse_resources(resources)
        return self.derive(resources=(*self.resources, *new_res))

    def derive(
        self,
        *,
        profile: str | Profile | None = None,
        backend: Backend | None = None,
        workspace: str | Path | None = None,
        writable: bool | None = None,
        resources: Iterable[str | Resource] | None = None,
        env: Mapping[str, str] | None = None,
        unshare_user: bool | None = None,
    ) -> Sandbox:
        """Return a branched Sandbox with overridden properties."""
        return Sandbox(
            profile=self.profile if profile is None else profile,
            backend=self.backend if backend is None else backend,
            workspace=self.workspace if workspace is None else workspace,
            writable=self.writable if writable is None else writable,
            resources=self.resources if resources is None else resources,
            env=self.env if env is None else env,
            unshare_user=self.unshare_user if unshare_user is None else unshare_user,
        )

    def build_spec(self, cmd: Sequence[str] = ()) -> SandboxSpec:
        """Compile profile and resources into an immutable SandboxSpec."""
        p = resolve_profile(self.profile)
        ctx = ProfileContext(
            cmd=cmd,
            env=self.env,
            workspace=self.workspace,
            writable=self.writable,
        )
        spec = p.apply(SandboxSpec(), ctx)
        if not self.unshare_user:
            spec = spec.with_namespaces(unshare_user=False)
        for res in self.resources:
            spec = res.apply(spec, self.env)
        return spec

    def compile(self, cmd: Sequence[str] = ()) -> list[str]:
        """Compile sandbox into target backend CLI arguments."""
        spec = self.build_spec(cmd)
        return self.backend.compile(spec, cmd)

    def build(self, cmd: Sequence[str] = ()) -> list[str]:
        """Alias for compile."""
        return self.compile(cmd)

    def wrap_command(self, cmd: Sequence[str] = ()) -> list[str]:
        """Compile and wrap command in backend arguments."""
        return self.compile(cmd)

    def create_builder(self, cmd: Sequence[str] = ()) -> Any:
        """Legacy compatibility helper: return a BubblewrapBuilder matching this configuration."""
        from hem.compat import create_sandbox

        return create_sandbox(
            cmd,
            workspace=self.workspace,
            writable=self.writable,
            resources=[type(r).__name__.lower() for r in self.resources],
            env=self.env,
        )

    def explain(self, cmd: Sequence[str] = ()) -> Explanation:
        """Audit the sandbox and return an Explanation breakdown."""
        spec = self.build_spec(cmd)
        mount_rows: list[tuple[str, str, str]] = []
        for m in spec.mounts:
            src = m.source or m.target
            mount_rows.append((m.kind.value, m.target, src))

        return Explanation(
            backend=self.backend.name,
            network=not spec.namespaces.unshare_net,
            namespaces=spec.namespaces.active_namespaces(),
            mounts=tuple(mount_rows),
            cwd=str(spec.cwd) if spec.cwd else None,
            env_keys=tuple(k for k, _ in spec.env),
        )

    def is_available(self) -> bool:
        """Check if the backend is available on the host."""
        return self.backend.is_available()

    def ensure_available(self) -> None:
        """Verify the backend is available, raising SandboxUnavailableError if not."""
        if not self.is_available():
            raise SandboxUnavailableError()

    def run(
        self,
        cmd: Sequence[str],
        *,
        capture_output: bool = False,
        check: bool = False,
        timeout: float | None = None,
        text: bool = False,
        input: str | bytes | None = None,
        stdin: int | IO[Any] | None = None,
        stdout: int | IO[Any] | None = None,
        stderr: int | IO[Any] | None = None,
    ) -> CompletedProcess[Any]:
        """Execute command in sandbox synchronously."""
        self.ensure_available()
        argv = self.compile(cmd)
        return run_argv(
            argv,
            env=self.env,
            cwd=self.workspace,
            timeout=timeout,
            capture_output=capture_output,
            check=check,
            text=text,
            input=input,
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
        )

    async def async_run(
        self,
        cmd: Sequence[str],
        *,
        capture_output: bool = False,
        check: bool = False,
        timeout: float | None = None,
        text: bool = False,
        input: str | bytes | None = None,
        stdin: int | None = None,
        stdout: int | None = None,
        stderr: int | None = None,
    ) -> CompletedProcess[Any]:
        """Execute command in sandbox asynchronously."""
        self.ensure_available()
        argv = self.compile(cmd)
        return await async_run_argv(
            argv,
            env=self.env,
            cwd=self.workspace,
            timeout=timeout,
            capture_output=capture_output,
            check=check,
            text=text,
            input=input,
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
        )

    def popen(
        self,
        cmd: Sequence[str],
        *,
        text: bool = False,
        stdin: int | IO[Any] | None = None,
        stdout: int | IO[Any] | None = None,
        stderr: int | IO[Any] | None = None,
    ) -> subprocess.Popen[Any]:
        """Spawn sandboxed process via subprocess.Popen."""
        self.ensure_available()
        argv = self.compile(cmd)
        return popen_argv(
            argv,
            env=self.env,
            cwd=self.workspace,
            text=text,
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
        )


import subprocess


def run(
    cmd: Sequence[str],
    *,
    profile: str | Profile = "strict",
    backend: Backend | None = None,
    workspace: str | Path | None = None,
    writable: bool = False,
    resources: Iterable[str | Resource] | None = None,
    env: Mapping[str, str] | None = None,
    capture_output: bool = False,
    check: bool = False,
    timeout: float | None = None,
    text: bool = False,
    input: str | bytes | None = None,
    stdin: int | IO[Any] | None = None,
    stdout: int | IO[Any] | None = None,
    stderr: int | IO[Any] | None = None,
) -> CompletedProcess[Any]:
    """Execute command in a sandbox configured by profile and resources."""
    box = Sandbox(
        profile=profile,
        backend=backend,
        workspace=workspace,
        writable=writable,
        resources=resources,
        env=env,
    )
    return box.run(
        cmd,
        capture_output=capture_output,
        check=check,
        timeout=timeout,
        text=text,
        input=input,
        stdin=stdin,
        stdout=stdout,
        stderr=stderr,
    )


async def async_run(
    cmd: Sequence[str],
    *,
    profile: str | Profile = "strict",
    backend: Backend | None = None,
    workspace: str | Path | None = None,
    writable: bool = False,
    resources: Iterable[str | Resource] | None = None,
    env: Mapping[str, str] | None = None,
    capture_output: bool = False,
    check: bool = False,
    timeout: float | None = None,
    text: bool = False,
    input: str | bytes | None = None,
    stdin: int | None = None,
    stdout: int | None = None,
    stderr: int | None = None,
) -> CompletedProcess[Any]:
    """Execute command in a sandbox asynchronously."""
    box = Sandbox(
        profile=profile,
        backend=backend,
        workspace=workspace,
        writable=writable,
        resources=resources,
        env=env,
    )
    return await box.async_run(
        cmd,
        capture_output=capture_output,
        check=check,
        timeout=timeout,
        text=text,
        input=input,
        stdin=stdin,
        stdout=stdout,
        stderr=stderr,
    )
