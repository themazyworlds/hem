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
