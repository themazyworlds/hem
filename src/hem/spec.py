"""
Hem • Sandbox specification.

Pure, immutable data describing *what* a sandbox should allow. Nothing in this module touches the
filesystem, the environment or any process, so a spec can be built, inspected, diffed, serialized and
unit-tested on any platform. Backends (see :mod:`hem.backends`) turn a spec into an enforceable command.
"""

from __future__ import annotations

import enum
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any


class MountKind(enum.Enum):
    """How a filesystem path or pseudofs is made visible inside the sandbox."""

    RO = "ro"
    RW = "rw"
    DEV_BIND = "dev_bind"
    TMPFS = "tmpfs"
    DEV = "dev"
    PROC = "proc"
    SYMLINK = "symlink"
    DIR = "dir"


@dataclass(frozen=True, slots=True)
class Mount:
    """A single filesystem mount or layout operation inside the container."""

    target: str
    kind: MountKind
    source: str | None = None
    try_ok: bool = False
    perms: int | None = None
    size: int | None = None

    def __post_init__(self) -> None:
        target_norm = str(Path(self.target)) if self.target != "/" else "/"
        if self.target != target_norm:
            object.__setattr__(self, "target", target_norm)
        if self.source is not None and self.kind not in (MountKind.SYMLINK, MountKind.TMPFS):
            source_norm = str(Path(self.source)) if self.source != "/" else "/"
            if self.source != source_norm:
                object.__setattr__(self, "source", source_norm)


@dataclass(frozen=True, slots=True)
class NamespaceSpec:
    """Linux kernel namespace isolation configuration."""

    unshare_user: bool = True
    unshare_pid: bool = True
    unshare_net: bool = True
    unshare_ipc: bool = True
    unshare_uts: bool = True
    unshare_cgroup: bool = True

    def active_namespaces(self) -> dict[str, bool]:
        """Return dict mapping namespace name to whether it is unshared."""
        return {
            "user": self.unshare_user,
            "pid": self.unshare_pid,
            "net": self.unshare_net,
            "ipc": self.unshare_ipc,
            "uts": self.unshare_uts,
            "cgroup": self.unshare_cgroup,
        }


@dataclass(frozen=True, slots=True)
class LimitSpec:
    """Resource constraints for sandboxed processes."""

    timeout: float | None = None
    max_output_bytes: int | None = None


@dataclass(frozen=True, slots=True)
class SandboxSpec:
    """
    Immutable specification of container sandbox capabilities and boundary parameters.
    """

    mounts: tuple[Mount, ...] = field(default_factory=tuple)
    env: tuple[tuple[str, str], ...] = field(default_factory=tuple)
    unset_env: tuple[str, ...] = field(default_factory=tuple)
    clean_env: bool = True
    namespaces: NamespaceSpec = field(default_factory=NamespaceSpec)
    cwd: Path | None = None
    die_with_parent: bool = True
    limits: LimitSpec = field(default_factory=LimitSpec)
    uid: int | None = None
    gid: int | None = None
    hostname: str | None = None

    def with_mount(
        self,
        kind: MountKind,
        target: str | Path,
        source: str | Path | None = None,
        *,
        try_ok: bool = False,
        perms: int | None = None,
        size: int | None = None,
    ) -> SandboxSpec:
        """Return a new SandboxSpec with an additional mount operation."""
        tgt = str(target)
        src = str(source) if source is not None else (tgt if kind in (MountKind.RO, MountKind.RW, MountKind.DEV_BIND) else None)
        mount = Mount(
            target=tgt,
            kind=kind,
            source=src,
            try_ok=try_ok,
            perms=perms,
            size=size,
        )
        return replace(self, mounts=(*self.mounts, mount))

    def with_ro_mount(self, source: str | Path, target: str | Path | None = None, *, try_ok: bool = False) -> SandboxSpec:
        """Convenience method to add a read-only bind mount."""
        tgt = target or source
        return self.with_mount(MountKind.RO, tgt, source, try_ok=try_ok)

    def with_rw_mount(self, source: str | Path, target: str | Path | None = None, *, try_ok: bool = False) -> SandboxSpec:
        """Convenience method to add a read-write bind mount."""
        tgt = target or source
        return self.with_mount(MountKind.RW, tgt, source, try_ok=try_ok)

    def with_tmpfs(self, target: str | Path, *, size: int | None = None) -> SandboxSpec:
        """Convenience method to add a tmpfs mount."""
        return self.with_mount(MountKind.TMPFS, target, size=size)

    def with_env(self, key: str, value: str | None) -> SandboxSpec:
        """Return a new SandboxSpec setting an environment variable."""
        if value is None:
            return self
        existing = dict(self.env)
        existing[key] = str(value)
        new_env = tuple((k, existing[k]) for k in sorted(existing.keys()))
        new_unset = tuple(k for k in self.unset_env if k != key)
        return replace(self, env=new_env, unset_env=new_unset)

    def with_env_vars(self, env_vars: Mapping[str, str | None]) -> SandboxSpec:
        """Return a new SandboxSpec setting multiple environment variables."""
        existing = dict(self.env)
        for k, v in env_vars.items():
            if v is not None:
                existing[k] = str(v)
        new_env = tuple((k, existing[k]) for k in sorted(existing.keys()))
        new_unset = tuple(k for k in self.unset_env if k not in existing)
        return replace(self, env=new_env, unset_env=new_unset)

    def without_env(self, key: str) -> SandboxSpec:
        """Return a new SandboxSpec explicitly unsetting an environment variable."""
        new_env = tuple((k, v) for k, v in self.env if k != key)
        if key not in self.unset_env:
            new_unset = (*self.unset_env, key)
        else:
            new_unset = self.unset_env
        return replace(self, env=new_env, unset_env=new_unset)

    def with_namespaces(
        self,
        *,
        unshare_user: bool | None = None,
        unshare_pid: bool | None = None,
        unshare_net: bool | None = None,
        unshare_ipc: bool | None = None,
        unshare_uts: bool | None = None,
        unshare_cgroup: bool | None = None,
    ) -> SandboxSpec:
        """Return a new SandboxSpec with modified namespace flags."""
        curr = self.namespaces
        new_ns = NamespaceSpec(
            unshare_user=unshare_user if unshare_user is not None else curr.unshare_user,
            unshare_pid=unshare_pid if unshare_pid is not None else curr.unshare_pid,
            unshare_net=unshare_net if unshare_net is not None else curr.unshare_net,
            unshare_ipc=unshare_ipc if unshare_ipc is not None else curr.unshare_ipc,
            unshare_uts=unshare_uts if unshare_uts is not None else curr.unshare_uts,
            unshare_cgroup=unshare_cgroup if unshare_cgroup is not None else curr.unshare_cgroup,
        )
        return replace(self, namespaces=new_ns)

    def with_cwd(self, cwd: str | Path | None) -> SandboxSpec:
        """Return a new SandboxSpec setting the container working directory."""
        return replace(self, cwd=Path(cwd) if cwd is not None else None)

    def with_limits(
        self,
        *,
        timeout: float | None = None,
        max_output_bytes: int | None = None,
    ) -> SandboxSpec:
        """Return a new SandboxSpec with updated limits."""
        curr = self.limits
        new_limits = LimitSpec(
            timeout=timeout if timeout is not None else curr.timeout,
            max_output_bytes=max_output_bytes if max_output_bytes is not None else curr.max_output_bytes,
        )
        return replace(self, limits=new_limits)

    def env_map(self) -> dict[str, str]:
        """Return container environment variables as a dictionary."""
        return dict(self.env)

    def as_dict(self) -> dict[str, Any]:
        """Serialize complete spec into a JSON-serializable dictionary."""
        return {
            "mounts": [
                {
                    "target": m.target,
                    "kind": m.kind.value,
                    "source": m.source,
                    "try_ok": m.try_ok,
                    "perms": m.perms,
                    "size": m.size,
                }
                for m in self.mounts
            ],
            "env": dict(self.env),
            "unset_env": list(self.unset_env),
            "clean_env": self.clean_env,
            "namespaces": self.namespaces.active_namespaces(),
            "cwd": str(self.cwd) if self.cwd else None,
            "die_with_parent": self.die_with_parent,
            "limits": {
                "timeout": self.limits.timeout,
                "max_output_bytes": self.limits.max_output_bytes,
            },
            "uid": self.uid,
            "gid": self.gid,
            "hostname": self.hostname,
        }
