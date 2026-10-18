"""
Unit tests for Hem high-level Sandbox and Resource APIs.
"""

import asyncio
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
