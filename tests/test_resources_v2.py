"""
Unit tests for typed sandbox resources and string parser.
"""


import pytest

from hem.errors import UnknownResourceError
from hem.resources import (
    DBusSession,
    DBusSystem,
    Display,
    Env,
    Net,
    Socket,
    Sound,
    expand,
    parse_resource,
    parse_resources,
)
from hem.spec import SandboxSpec


def test_expand_with_explicit_env():
    env = {"HOME": "/custom/home", "RUNTIME": "/run/user/1000"}
    assert expand("~/config", env) == "/custom/home/config"
    assert expand("$RUNTIME/bus", env) == "/run/user/1000/bus"
    assert expand("${RUNTIME}/pipewire-0", env) == "/run/user/1000/pipewire-0"
    # Unknown variables are left alone
    assert expand("$UNKNOWN_VAR/file", env) == "$UNKNOWN_VAR/file"


def test_net_resource():
    spec = SandboxSpec()
    assert spec.namespaces.unshare_net is True
    applied = Net().apply(spec, {})
    assert applied.namespaces.unshare_net is False


def test_dbus_session_resource():
    env = {"XDG_RUNTIME_DIR": "/run/user/1000", "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus"}
    spec = SandboxSpec()
    applied = DBusSession().apply(spec, env)

    targets = [m.target for m in applied.mounts]
    assert "/run/user/1000/bus" in targets
    # Crucial security assertion: the runtime dir itself must NOT be mounted
    assert "/run/user/1000" not in targets
    assert applied.env_map()["DBUS_SESSION_BUS_ADDRESS"] == "unix:path=/run/user/1000/bus"


def test_display_resource():
    env = {"WAYLAND_DISPLAY": "wayland-0", "XDG_RUNTIME_DIR": "/run/user/1000", "DISPLAY": ":0"}
    spec = SandboxSpec()
    applied = Display().apply(spec, env)

    targets = [m.target for m in applied.mounts]
    assert "/run/user/1000/wayland-0" in targets
    assert "/tmp/.X11-unix" in targets
    assert applied.env_map()["WAYLAND_DISPLAY"] == "wayland-0"
    assert applied.env_map()["DISPLAY"] == ":0"


def test_parse_resource_exact_matching():
    assert isinstance(parse_resource("net"), Net)
    assert isinstance(parse_resource("network"), Net)
    assert isinstance(parse_resource("display"), Display)
    assert isinstance(parse_resource("dbus:session"), DBusSession)
    assert isinstance(parse_resource("dbus:system"), DBusSystem)
    assert isinstance(parse_resource("sound"), Sound)
    assert isinstance(parse_resource("socket:/tmp/test.sock"), Socket)
    assert isinstance(parse_resource("socket:rw:/tmp/test.sock"), Socket)
    assert isinstance(parse_resource("env:MY_VAR=123"), Env)

    # Sockets with 'net' in their path are parsed as Socket, never as Net
    sock_res = parse_resource("socket:/run/NetworkManager/x.sock")
    assert isinstance(sock_res, Socket)
    # Applying it does NOT unshare net
    spec = sock_res.apply(SandboxSpec(), {})
    assert spec.namespaces.unshare_net is True

    # Real unknown resources raise UnknownResourceError
    with pytest.raises(UnknownResourceError):
        parse_resource("dotnet")
    with pytest.raises(UnknownResourceError):
        parse_resource("internet")


def test_parse_resources_list():
    res = parse_resources(["net", "display", Net()])
    assert len(res) == 3
    assert all(isinstance(r, (Net, Display)) for r in res)
