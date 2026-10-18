"""
Hem • Bubblewrap (bwrap) Backend Compiler.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from hem.spec import Mount, MountKind, SandboxSpec


def _mount_sort_key(m: Mount) -> tuple[int, int, str]:
    """
    Sort mounts to ensure parent directories and tmpfs roots are mounted
    before child files or nested directories. Symlinks are created last.
    """
    p = Path(m.target)
    depth = len(p.parts)
    type_priority = 1
    if m.kind in (MountKind.DEV, MountKind.PROC):
        type_priority = 0
    elif m.kind == MountKind.TMPFS:
        type_priority = 1
    elif m.kind in (MountKind.RO, MountKind.RW, MountKind.DEV_BIND):
        type_priority = 2
    elif m.kind == MountKind.DIR:
        type_priority = 3
    elif m.kind == MountKind.SYMLINK:
        type_priority = 4

    return (depth, type_priority, m.target)


class BubblewrapBackend:
    """Compiles an immutable SandboxSpec into an executable bubblewrap CLI command."""

    name: str = "bwrap"
    _AVAILABLE: bool | None = None

    def __init__(self, bwrap_path: str | Path | None = None) -> None:
        self.bwrap_path = str(bwrap_path) if bwrap_path else (shutil.which("bwrap") or "bwrap")

    def is_available(self) -> bool:
        """Check if bubblewrap (bwrap) executable is present and working on the host."""
        if BubblewrapBackend._AVAILABLE is not None:
            return BubblewrapBackend._AVAILABLE

        if sys.platform != "linux":
            BubblewrapBackend._AVAILABLE = False
            return False

        bwrap_path = shutil.which(self.bwrap_path) or self.bwrap_path
        if not bwrap_path or not shutil.which(bwrap_path):
            BubblewrapBackend._AVAILABLE = False
            return False

        try:
            res = subprocess.run(
                [bwrap_path, "--version"],
                capture_output=True,
                text=True,
                timeout=2.0,
                check=False,
            )
            BubblewrapBackend._AVAILABLE = res.returncode == 0
            return BubblewrapBackend._AVAILABLE
        except (OSError, subprocess.SubprocessError):
            BubblewrapBackend._AVAILABLE = False
            return False

    def compile(self, spec: SandboxSpec, cmd: Sequence[str] = ()) -> list[str]:
        """Translate SandboxSpec and command tokens into Bubblewrap CLI flags."""
        tokens: list[str] = [self.bwrap_path]

        if spec.clean_env:
            tokens.append("--clearenv")

        # Sort mounts to guarantee deterministic and safe ordering
        sorted_mounts = sorted(spec.mounts, key=_mount_sort_key)
        for m in sorted_mounts:
            src = m.source or m.target
            if m.kind == MountKind.RO:
                flag = "--ro-bind-try" if m.try_ok else "--ro-bind"
                tokens.extend([flag, src, m.target])
            elif m.kind == MountKind.RW:
                flag = "--bind-try" if m.try_ok else "--bind"
                tokens.extend([flag, src, m.target])
            elif m.kind == MountKind.DEV_BIND:
                flag = "--dev-bind-try" if m.try_ok else "--dev-bind"
                tokens.extend([flag, src, m.target])
            elif m.kind == MountKind.TMPFS:
                tokens.extend(["--tmpfs", m.target])
                if m.size is not None:
                    tokens.extend(["--size", str(m.size)])
                if m.perms is not None:
                    tokens.extend(["--perms", oct(m.perms)[2:]])
            elif m.kind == MountKind.DEV:
                tokens.extend(["--dev", m.target])
            elif m.kind == MountKind.PROC:
                tokens.extend(["--proc", m.target])
            elif m.kind == MountKind.SYMLINK:
                tokens.extend(["--symlink", src, m.target])
            elif m.kind == MountKind.DIR:
                tokens.extend(["--dir", m.target])

        # Namespaces
        ns = spec.namespaces
        if ns.unshare_user:
            tokens.append("--unshare-user")
        if ns.unshare_ipc:
            tokens.append("--unshare-ipc")
        if ns.unshare_pid:
            tokens.append("--unshare-pid")
        if ns.unshare_net:
            tokens.append("--unshare-net")
        if ns.unshare_uts:
            tokens.append("--unshare-uts")
        if ns.unshare_cgroup:
            tokens.append("--unshare-cgroup-try")

        if spec.die_with_parent:
            tokens.append("--die-with-parent")

        if spec.cwd is not None:
            tokens.extend(["--chdir", str(spec.cwd)])

        if spec.uid is not None:
            tokens.extend(["--uid", str(spec.uid)])
        if spec.gid is not None:
            tokens.extend(["--gid", str(spec.gid)])
        if spec.hostname is not None:
            tokens.extend(["--hostname", spec.hostname])

        # In-container environment variables
        for k, v in spec.env:
            tokens.extend(["--setenv", k, v])

        for k in spec.unset_env:
            tokens.extend(["--unsetenv", k])

        if cmd:
            tokens.extend(cmd)

        return tokens
