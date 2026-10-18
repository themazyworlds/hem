"""
Hem • Typed sandbox resources.

A resource is a declarative grant ("this sandbox may use the network / the Wayland display / this socket").
Each one is a small object that turns a :class:`~hem.spec.SandboxSpec` into a new one. Resources resolve
against an *explicit* environment mapping and never read ``os.environ`` themselves.

Resources only ever add the narrowest thing that satisfies the grant: ``DBusSession`` binds the bus socket,
not the runtime directory that contains it. Third parties can add their own with :func:`register_resource`.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from hem.errors import UnknownResourceError
from hem.spec import MountKind, SandboxSpec


@runtime_checkable
class Resource(Protocol):
    """Anything that can grant access by transforming a spec."""

    def apply(self, spec: SandboxSpec, env: Mapping[str, str]) -> SandboxSpec:
        """Apply resource grants to spec using explicit environment mapping."""
        ...


def expand(value: str, env: Mapping[str, str]) -> str:
    """Expand ``$VAR``/``${VAR}`` and leading ``~`` using ``env`` only. Unknown variables are left as-is."""
    if value.startswith("~") and (value == "~" or value.startswith("~/")):
        home = env.get("HOME", "")
        value = home + value[1:] if home else value

    def _replace_var(match: re.Match[str]) -> str:
        var_name = match.group(1) or match.group(2)
        return env.get(var_name, match.group(0))

    return re.sub(r"\$(?:([A-Za-z0-9_]+)|\{([A-Za-z0-9_]+)\})", _replace_var, value)


@dataclass(frozen=True, slots=True)
class Net:
    """Grants access to the host network namespace."""

    def apply(self, spec: SandboxSpec, env: Mapping[str, str]) -> SandboxSpec:
        return spec.with_namespaces(unshare_net=False)


@dataclass(frozen=True, slots=True)
class Display:
    """Grants access to Wayland and/or X11 display servers."""

    wayland: bool = True
    x11: bool = True

    def apply(self, spec: SandboxSpec, env: Mapping[str, str]) -> SandboxSpec:
        new_spec = spec
        if self.wayland:
            wayland_display = env.get("WAYLAND_DISPLAY")
            runtime = env.get("XDG_RUNTIME_DIR")
            if wayland_display and runtime:
                wl_sock = os.path.join(runtime, wayland_display)
                new_spec = (
                    new_spec.with_ro_mount(wl_sock, try_ok=True)
                    .with_env("WAYLAND_DISPLAY", wayland_display)
                    .with_env("XDG_RUNTIME_DIR", runtime)
                )

        if self.x11:
            x11_display = env.get("DISPLAY")
            if x11_display:
                new_spec = new_spec.with_env("DISPLAY", x11_display).with_ro_mount("/tmp/.X11-unix", try_ok=True)

        return new_spec


@dataclass(frozen=True, slots=True)
class DBusSession:
    """
    Grants access to the D-Bus session bus.
    Binds the specific session socket file ONLY; never exposes the containing runtime directory.
    """

    bus_address: str | None = None

    def apply(self, spec: SandboxSpec, env: Mapping[str, str]) -> SandboxSpec:
        addr = self.bus_address or env.get("DBUS_SESSION_BUS_ADDRESS")
        runtime = env.get("XDG_RUNTIME_DIR")
        new_spec = spec

        if addr:
            new_spec = new_spec.with_env("DBUS_SESSION_BUS_ADDRESS", addr)
            if "unix:path=" in addr:
                sock_path = addr.split("unix:path=")[1].split(",")[0]
                new_spec = new_spec.with_ro_mount(sock_path, try_ok=True)
        elif runtime:
            default_bus = os.path.join(runtime, "bus")
            new_spec = (
                new_spec.with_ro_mount(default_bus, try_ok=True)
                .with_env("DBUS_SESSION_BUS_ADDRESS", f"unix:path={default_bus}")
            )

        if runtime:
            new_spec = new_spec.with_env("XDG_RUNTIME_DIR", runtime)

        return new_spec


@dataclass(frozen=True, slots=True)
class DBusSystem:
    """Grants access to the D-Bus system bus socket."""

    bus_path: str = "/run/dbus/system_bus_socket"

    def apply(self, spec: SandboxSpec, env: Mapping[str, str]) -> SandboxSpec:
        return spec.with_ro_mount(self.bus_path, try_ok=True)


@dataclass(frozen=True, slots=True)
class Sound:
    """Grants access to PipeWire and/or PulseAudio audio daemons."""

    pipewire: bool = True
    pulse: bool = True

    def apply(self, spec: SandboxSpec, env: Mapping[str, str]) -> SandboxSpec:
        runtime = env.get("XDG_RUNTIME_DIR")
        if not runtime:
            return spec

        new_spec = spec
        if self.pipewire:
            pw_sock = os.path.join(runtime, "pipewire-0")
            new_spec = new_spec.with_ro_mount(pw_sock, try_ok=True)
        if self.pulse:
            pulse_dir = os.path.join(runtime, "pulse")
            new_spec = new_spec.with_ro_mount(pulse_dir, try_ok=True)

        return new_spec


@dataclass(frozen=True, slots=True)
class Socket:
    """Grants access to an arbitrary Unix domain socket file or socket directory."""

    path: str
    writable: bool = False
    try_ok: bool = True

    def apply(self, spec: SandboxSpec, env: Mapping[str, str]) -> SandboxSpec:
        expanded_path = expand(self.path, env)
        kind = MountKind.RW if self.writable else MountKind.RO
        return spec.with_mount(kind, expanded_path, expanded_path, try_ok=self.try_ok)


@dataclass(frozen=True, slots=True)
class PathGrant:
    """Grants access to a host filesystem path."""

    path: str
    target: str | None = None
    writable: bool = False
    try_ok: bool = True

    def apply(self, spec: SandboxSpec, env: Mapping[str, str]) -> SandboxSpec:
        expanded_src = expand(self.path, env)
        expanded_tgt = expand(self.target, env) if self.target is not None else expanded_src
        kind = MountKind.RW if self.writable else MountKind.RO
        return spec.with_mount(kind, expanded_tgt, expanded_src, try_ok=self.try_ok)


@dataclass(frozen=True, slots=True)
class Env:
    """Injects or passes through an environment variable into the container."""

    name: str
    value: str | None = None

    def apply(self, spec: SandboxSpec, env: Mapping[str, str]) -> SandboxSpec:
        val = self.value if self.value is not None else env.get(self.name)
        if val is not None:
            return spec.with_env(self.name, val)
        return spec


_RESOURCE_REGISTRY: dict[str, Callable[[str], Resource]] = {}


def register_resource(name: str, factory: Callable[[str], Resource]) -> None:
    """Register a custom resource parser factory."""
    _RESOURCE_REGISTRY[name.lower().strip()] = factory


def parse_resource(token: str | Resource) -> Resource:
    """Parse a typed resource instance or declarative string token."""
    if isinstance(token, Resource):
        return token

    clean = token.strip()
    lowered = clean.lower()

    if lowered in ("net", "network"):
        return Net()
    if lowered == "display":
        return Display()
    if lowered in ("display:wayland", "wayland"):
        return Display(wayland=True, x11=False)
    if lowered in ("display:x11", "x11"):
        return Display(wayland=False, x11=True)
    if lowered in ("dbus:session", "dbus-session"):
        return DBusSession()
    if lowered in ("dbus:system", "dbus-system"):
        return DBusSystem()
    if lowered == "sound":
        return Sound()
    if lowered in ("sound:pipewire", "pipewire"):
        return Sound(pipewire=True, pulse=False)
    if lowered in ("sound:pulse", "sound:pulseaudio", "pulse"):
        return Sound(pipewire=False, pulse=True)

    if lowered.startswith("socket:rw:"):
        return Socket(clean[10:].strip(), writable=True)
    if lowered.startswith("socket:"):
        return Socket(clean[7:].strip(), writable=False)

    if lowered.startswith("path:rw:"):
        return PathGrant(clean[8:].strip(), writable=True)
    if lowered.startswith("path:"):
        return PathGrant(clean[5:].strip(), writable=False)

    if lowered.startswith("env:"):
        rem = clean[4:].strip()
        if "=" in rem:
            k, v = rem.split("=", 1)
            return Env(k.strip(), v.strip())
        return Env(rem)

    # Check custom registry
    prefix = lowered.split(":", 1)[0]
    if prefix in _RESOURCE_REGISTRY:
        return _RESOURCE_REGISTRY[prefix](clean)

    raise UnknownResourceError(f"Unrecognized sandbox resource token: '{token}'")


def parse_resources(tokens: Iterable[str | Resource] | None) -> tuple[Resource, ...]:
    """Parse an iterable of string specifiers or Resource objects into a typed tuple."""
    if not tokens:
        return ()
    return tuple(parse_resource(t) for t in tokens)
