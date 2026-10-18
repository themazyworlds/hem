"""
Unit tests for Hem high-level Sandbox and Resource APIs.
"""

import asyncio
import os
from pathlib import Path

import pytest

from hem import (
    BubblewrapBuilder,
    Sandbox,
    allows_network,
    apply_resources,
    async_run_sandboxed,
    create_sandbox,
    is_available,
    requires_host_session,
    run_sandboxed,
    wrap_command,
)


def test_is_available():
    avail = is_available()
    assert isinstance(avail, bool)


def test_resource_helpers():
    assert allows_network(["net"]) is True
    assert allows_network(["network"]) is True
    assert allows_network(["display"]) is False
    assert allows_network(["socket:/run/NetworkManager/x.sock"]) is False
    assert allows_network(["socket:/run/systemd/netif/leases"]) is False
    assert allows_network(["internet"]) is False
    assert allows_network(["dotnet"]) is False
    assert allows_network(["net "]) is True
    assert allows_network(["network "]) is True

    assert requires_host_session(["display"]) is True
    assert requires_host_session(["dbus:session"]) is True
    assert requires_host_session(["net"]) is False


def test_apply_resources():
    builder = BubblewrapBuilder("/usr/bin/bwrap")
    resources = [
        "display",
        "sound",
        "dbus:session",
        "dbus:system",
        "net",
        "env:MY_VAR=hello",
        "socket:/tmp",
    ]
    apply_resources(builder, resources)
    built = builder.build()
    assert "--setenv" in built
    assert "MY_VAR" in built
    assert "hello" in built
    # dbus:session must NOT bind the full XDG_RUNTIME_DIR read-write
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if runtime:
        bind_indices = [i for i, val in enumerate(built) if val == "--bind"]
        for idx in bind_indices:
            assert built[idx + 1] != runtime


def test_create_sandbox_and_wrap_command(tmp_path: Path):
    cmd = ["python", "-c", "print(1)"]
    builder = create_sandbox(
        cmd,
        workspace=tmp_path,
        writable=True,
        resources=["net"],
        extra_ro_binds=[tmp_path],
    )
    wrapped = wrap_command(
        cmd,
        workspace=tmp_path,
        writable=True,
        resources=["net"],
    )

    assert isinstance(builder, BubblewrapBuilder)
    assert isinstance(wrapped, list)
    assert wrapped[0] == builder.args[0]
    assert "--unshare-net" not in wrapped
    assert str(tmp_path.resolve()) in wrapped


def test_sandbox_class(tmp_path: Path):
    box = Sandbox(
        workspace=tmp_path,
        writable=False,
        resources=["display"],
    )
    cmd = ["python", "-c", "print('sandbox')"]
    builder = box.create_builder(cmd)
    wrapped = box.wrap_command(cmd)

    assert isinstance(builder, BubblewrapBuilder)
    assert "--ro-bind" in wrapped
    assert str(tmp_path.resolve()) in wrapped
    assert box.is_available() == is_available()
    # Host session resources must preserve pid namespace isolation
    assert "--unshare-pid" in wrapped
    assert "--unshare-user" not in wrapped


def test_run_sandboxed_execution():
    if not is_available():
        pytest.skip("bwrap not available in current test environment")

    res = run_sandboxed(["echo", "hem-sandboxed"], capture_output=True, text=True)
    assert res.returncode == 0
    assert "hem-sandboxed" in res.stdout


def test_async_run_sandboxed_execution():
    if not is_available():
        pytest.skip("bwrap not available in current test environment")

    async def _test():
        res = await async_run_sandboxed(["echo", "hem-async-sandboxed"], capture_output=True, text=True)
        assert res.returncode == 0
        assert "hem-async-sandboxed" in res.stdout

    asyncio.run(_test())
