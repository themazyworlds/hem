"""
Hem • Reusable policy profiles.

A profile is a named, composable policy transform: given the spec built so far and a :class:`ProfileContext`
(the command, the host environment, the workspace) it returns a new spec. Profiles may probe the filesystem
to decide what exists; the spec and backends never do.

Presets:
  ``minimal``  system base, workspace, standard environment
  ``strict``   minimal + the executable's own install root, and the Python runtime when the command is Python
  ``desktop``  strict + passthrough of desktop session variables (still no extra filesystem or socket access)
"""

from __future__ import annotations

import contextlib
import os
import shutil
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

from hem.errors import ProfileError
from hem.spec import MountKind, SandboxSpec


@dataclass(frozen=True, slots=True)
class ProfileContext:
    """Contextual metadata passed to a profile during sandbox generation."""

    cmd: Sequence[str] = field(default_factory=tuple)
    env: Mapping[str, str] = field(default_factory=dict)
    workspace: Path | None = None
    writable: bool = False
    extra_ro_binds: tuple[str | Path, ...] = field(default_factory=tuple)
    extra_binds: tuple[str | Path, ...] = field(default_factory=tuple)


@runtime_checkable
class Profile(Protocol):
    """Protocol for sandbox policy profiles."""

    def apply(self, spec: SandboxSpec, ctx: ProfileContext) -> SandboxSpec:
        """Apply profile policy to sandbox specification."""
        ...


def system_base_profile(spec: SandboxSpec, ctx: ProfileContext) -> SandboxSpec:
    """Mount base Linux filesystem hierarchy, standard symlinks, and minimal dev/proc."""
    lib64_target = "usr/lib64" if Path("/usr/lib64").exists() else "usr/lib"

    new_spec = (
        spec.with_mount(MountKind.RO, "/usr", "/usr")
        .with_mount(MountKind.SYMLINK, "/lib64", lib64_target)
        .with_mount(MountKind.SYMLINK, "/lib", "usr/lib")
        .with_mount(MountKind.SYMLINK, "/bin", "usr/bin")
        .with_mount(MountKind.SYMLINK, "/sbin", "usr/bin")
    )

    for sys_dir in ("/etc", "/sys", "/opt", "/nix"):
        if Path(sys_dir).exists():
            new_spec = new_spec.with_mount(MountKind.RO, sys_dir, sys_dir, try_ok=True)

    new_spec = (
        new_spec.with_mount(MountKind.DEV, "/dev")
        .with_mount(MountKind.PROC, "/proc")
        .with_mount(MountKind.TMPFS, "/tmp")
        .with_mount(MountKind.TMPFS, "/home")
    )

    # Standard minimal environment variables inside container
    user_name = ctx.env.get("USER", os.getenv("USER", "user"))
    home_dir = ctx.env.get("HOME", os.getenv("HOME", f"/home/{user_name}"))
    new_spec = new_spec.with_env_vars(
        {
            "PATH": ctx.env.get("PATH", "/usr/bin:/bin"),
            "HOME": home_dir,
            "USER": user_name,
            "TERM": ctx.env.get("TERM", "xterm-256color"),
            "TMPDIR": "/tmp",
        }
    )

    return new_spec


def workspace_profile(spec: SandboxSpec, ctx: ProfileContext) -> SandboxSpec:
    """Mount workspace directory and set working directory."""
    new_spec = spec
    if ctx.workspace:
        ws_resolved = Path(ctx.workspace).resolve()
        if ws_resolved.exists():
            kind = MountKind.RW if ctx.writable else MountKind.RO
            new_spec = new_spec.with_mount(kind, ws_resolved, ws_resolved)
            new_spec = new_spec.with_cwd(ws_resolved)

    for ro_p in ctx.extra_ro_binds:
        p_obj = Path(ro_p).resolve()
        if p_obj.exists():
            new_spec = new_spec.with_mount(MountKind.RO, p_obj, p_obj, try_ok=True)

    for rw_p in ctx.extra_binds:
        p_obj = Path(rw_p).resolve()
        if p_obj.exists():
            new_spec = new_spec.with_mount(MountKind.RW, p_obj, p_obj, try_ok=True)

    return new_spec


def python_runtime_profile(spec: SandboxSpec, ctx: ProfileContext) -> SandboxSpec:
    """Mount Python virtualenv roots, sys.path packages, and executable dependency locations."""
    new_spec = spec

    # Mount Python interpreter virtual environment prefix if active
    for check_path in (sys.prefix, sys.base_prefix, getattr(sys, "base_exec_prefix", None)):
        if check_path and Path(check_path).exists():
            p_resolved = Path(check_path).resolve()
            p_str = str(p_resolved)
            if not any(p_str.startswith(prefix) for prefix in ("/usr", "/lib", "/opt", "/nix")):
                new_spec = new_spec.with_mount(MountKind.RO, p_resolved, p_resolved, try_ok=True)

    # Mount sys.path entries outside system directories
    sys_temp = tempfile.gettempdir()
    ignored_prefixes = ("/usr", "/lib", "/opt", "/nix", sys_temp)
    for entry in sys.path:
        if entry and Path(entry).exists():
            p_res = Path(entry).resolve()
            p_str = str(p_res)
            if not any(p_str.startswith(prefix) for prefix in ignored_prefixes):
                target = p_res.parent if p_res.name == "src" else p_res
                new_spec = new_spec.with_mount(MountKind.RO, target, target, try_ok=True)

    # If the command invokes a Python binary or script, bind dependencies
    if ctx.cmd:
        exe_name = ctx.cmd[0]
        exe_target = shutil.which(exe_name) or exe_name
        if Path(exe_target).exists():
            raw_path = str(Path(exe_target).absolute())
            resolved_path = str(Path(exe_target).resolve())
            for p_str in (raw_path, resolved_path):
                if ".venv" in p_str:
                    venv_root = p_str.split("/bin/")[0]
                    new_spec = new_spec.with_mount(MountKind.RO, venv_root, venv_root, try_ok=True)
                    with contextlib.suppress(OSError):
                        for pth in Path(venv_root).glob("lib*/python*/site-packages/*.pth"):
                            for line in pth.read_text(encoding="utf-8").splitlines():
                                target_line = line.strip()
                                if target_line and not target_line.startswith(("#", "import ")):
                                    p_pth = Path(target_line).resolve()
                                    if p_pth.exists():
                                        bind_tgt = p_pth.parent if p_pth.name == "src" else p_pth
                                        new_spec = new_spec.with_mount(MountKind.RO, bind_tgt, bind_tgt, try_ok=True)
                if p_str.startswith(str(Path.home() / ".local")):
                    local_p = Path.home() / ".local"
                    if local_p.exists():
                        new_spec = new_spec.with_mount(MountKind.RO, local_p, local_p, try_ok=True)

        for arg in ctx.cmd:
            if "\n" in arg or len(arg) > 255:
                continue
            with contextlib.suppress(OSError):
                if arg.endswith(".py") or Path(arg).exists():
                    p_arg = Path(arg).resolve()
                    if p_arg.is_file():
                        new_spec = new_spec.with_mount(MountKind.RO, p_arg.parent, p_arg.parent, try_ok=True)
                    elif p_arg.is_dir():
                        new_spec = new_spec.with_mount(MountKind.RO, p_arg, p_arg, try_ok=True)

    pythonpath = ctx.env.get("PYTHONPATH")
    if pythonpath:
        new_spec = new_spec.with_env("PYTHONPATH", pythonpath)
        for p in pythonpath.split(":"):
            if p and Path(p).exists():
                p_res = Path(p).resolve()
                new_spec = new_spec.with_mount(MountKind.RO, p_res, p_res, try_ok=True)

    return new_spec


class FunctionalProfile:
    """Wrapper that adapts a Callable[[SandboxSpec, ProfileContext], SandboxSpec] to the Profile protocol."""

    def __init__(self, fn: Callable[[SandboxSpec, ProfileContext], SandboxSpec]) -> None:
        self._fn = fn

    def apply(self, spec: SandboxSpec, ctx: ProfileContext) -> SandboxSpec:
        return self._fn(spec, ctx)


def minimal_profile(spec: SandboxSpec, ctx: ProfileContext) -> SandboxSpec:
    """Minimal policy: base system mounts and isolated workspace."""
    s = system_base_profile(spec, ctx)
    return workspace_profile(s, ctx)


def strict_profile(spec: SandboxSpec, ctx: ProfileContext) -> SandboxSpec:
    """Strict policy: minimal profile + executable dependencies and Python runtime."""
    s = minimal_profile(spec, ctx)
    return python_runtime_profile(s, ctx)


def desktop_profile(spec: SandboxSpec, ctx: ProfileContext) -> SandboxSpec:
    """Desktop policy: strict profile + passthrough of desktop environment variables."""
    s = strict_profile(spec, ctx)
    desktop_keys = (
        "XDG_RUNTIME_DIR",
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
        "XDG_CACHE_HOME",
        "TERMINAL",
    )
    for k in desktop_keys:
        if v := ctx.env.get(k):
            s = s.with_env(k, v)
    return s


_BUILTIN_PROFILES: dict[str, Profile] = {
    "minimal": FunctionalProfile(minimal_profile),
    "strict": FunctionalProfile(strict_profile),
    "desktop": FunctionalProfile(desktop_profile),
}


def register_profile(name: str, profile: Profile | Callable[[SandboxSpec, ProfileContext], SandboxSpec]) -> None:
    """Register a custom sandbox policy profile."""
    p = profile if isinstance(profile, Profile) else FunctionalProfile(profile)
    _BUILTIN_PROFILES[name.lower().strip()] = p


def resolve_profile(name_or_profile: str | Profile) -> Profile:
    """Resolve a profile name or return an existing Profile instance."""
    if isinstance(name_or_profile, Profile):
        return name_or_profile

    clean = name_or_profile.lower().strip()
    if clean in _BUILTIN_PROFILES:
        return _BUILTIN_PROFILES[clean]

    raise ProfileError(f"Unknown sandbox profile: '{name_or_profile}'. Available: {list(_BUILTIN_PROFILES.keys())}")
