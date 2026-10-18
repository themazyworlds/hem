"""
Unit tests for Hem BubblewrapBuilder.
"""

from hem import BubblewrapBuilder


def test_builder_primitives():
    builder = (
        BubblewrapBuilder("/usr/bin/bwrap")
        .clearenv()
        .setenv("FOO", "BAR")
        .unsetenv("BAZ")
        .ro_bind("/etc", try_ok=True)
        .bind("/tmp")
        .dev_bind("/dev/null")
        .tmpfs("/run")
        .dev("/dev")
        .proc("/proc")
        .symlink("usr/bin", "/bin")
        .dir("/var/log")
        .chdir("/tmp")
        .unshare("user", "net")
        .die_with_parent()
    )
    cmd = builder.build(["echo", "hello"])

    assert cmd[0] == "/usr/bin/bwrap"
    assert "--clearenv" in cmd
    assert cmd[2:5] == ["--setenv", "FOO", "BAR"]
    assert cmd[5:7] == ["--unsetenv", "BAZ"]
    assert cmd[7:10] == ["--ro-bind-try", "/etc", "/etc"]
    assert cmd[10:13] == ["--bind", "/tmp", "/tmp"]
    assert cmd[13:16] == ["--dev-bind", "/dev/null", "/dev/null"]
    assert cmd[16:18] == ["--tmpfs", "/run"]
    assert cmd[18:20] == ["--dev", "/dev"]
    assert cmd[20:22] == ["--proc", "/proc"]
    assert cmd[22:25] == ["--symlink", "usr/bin", "/bin"]
    assert cmd[25:27] == ["--dir", "/var/log"]
    assert cmd[27:29] == ["--chdir", "/tmp"]
    assert "--unshare-user" in cmd
    assert "--unshare-net" in cmd
    assert "--die-with-parent" in cmd
    assert cmd[-2:] == ["echo", "hello"]


def test_builder_composite_methods():
    builder = (
        BubblewrapBuilder("/usr/bin/bwrap")
        .bind_system_base()
        .bind_tmpfs_paths(["/tmp", "/run"])
        .set_namespaces(allow_network=True, unshare_user=False)
        .bind_workspace("/tmp", writable=True)
    )
    cmd = builder.build()

    assert "--ro-bind" in cmd
    assert "/usr" in cmd
    assert "--tmpfs" in cmd
    assert "--chdir" in cmd
    assert "--unshare-user" not in cmd
    assert "--unshare-net" not in cmd
    assert "--die-with-parent" in cmd


def test_builder_copy():
    base = BubblewrapBuilder("/usr/bin/bwrap").clearenv().ro_bind("/usr")
    cloned = base.copy().setenv("KEY", "VALUE")

    assert "--setenv" not in base.args
    assert "--setenv" in cloned.args
    assert "KEY" in cloned.args


def test_is_available():
    avail = BubblewrapBuilder.is_available()
    assert isinstance(avail, bool)


def test_run_execution():
    builder = BubblewrapBuilder("echo")
    res = builder.run(["hem-run-test"], capture_output=True, text=True)
    assert res.returncode == 0
    assert "hem-run-test" in res.stdout


def test_async_run_execution():
    import asyncio

    async def _test():
        builder = BubblewrapBuilder("echo")
        res = await builder.async_run(["hem-async-test"], capture_output=True, text=True)
        assert res.returncode == 0
        assert "hem-async-test" in res.stdout

    asyncio.run(_test())


def test_async_run_timeout():
    import asyncio
    import subprocess

    import pytest

    async def _test():
        builder = BubblewrapBuilder("sleep")
        with pytest.raises(subprocess.TimeoutExpired):
            await builder.async_run(["5"], timeout=0.05)

    asyncio.run(_test())


def test_top_level_command_runners():
    import asyncio

    from hem import async_run_command, run_command

    res = run_command(["echo", "direct-run"], capture_output=True, text=True)
    assert res.returncode == 0
    assert "direct-run" in res.stdout

    async def _test():
        a_res = await async_run_command(["echo", "direct-async"], capture_output=True, text=True)
        assert a_res.returncode == 0
        assert "direct-async" in a_res.stdout

    asyncio.run(_test())

