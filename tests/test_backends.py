"""
Unit tests for Bubblewrap and DryRun backends.
"""

from hem.backends.bwrap import BubblewrapBackend
from hem.backends.dry_run import DryRunBackend
from hem.spec import SandboxSpec


def test_dry_run_backend():
    spec = SandboxSpec().with_ro_mount("/usr").with_env("KEY", "val")
    backend = DryRunBackend()
    assert backend.is_available() is True
    cmd = backend.compile(spec, ["python", "app.py"])
    assert cmd[0] == "dry-run"
    assert "app.py" in cmd
    assert any("--spec" in token for token in cmd)


def test_bwrap_backend_compilation():
    spec = (
        SandboxSpec()
        .with_ro_mount("/usr")
        .with_tmpfs("/tmp")
        .with_env("MY_ENV", "123")
        .with_cwd("/tmp")
        .with_namespaces(unshare_net=True, unshare_pid=True)
    )
    backend = BubblewrapBackend("/usr/bin/bwrap")
    cmd = backend.compile(spec, ["echo", "hi"])

    assert cmd[0] == "/usr/bin/bwrap"
    assert "--clearenv" in cmd
    assert "--ro-bind" in cmd
    assert "/usr" in cmd
    assert "--tmpfs" in cmd
    assert "/tmp" in cmd
    assert "--unshare-net" in cmd
    assert "--unshare-pid" in cmd
    assert "--setenv" in cmd
    assert "MY_ENV" in cmd
    assert "123" in cmd
    assert cmd[-2:] == ["echo", "hi"]


def test_bwrap_mount_ordering():
    # /home must be mounted before /home/user/project
    spec = (
        SandboxSpec()
        .with_ro_mount("/home/user/project", "/home/user/project")
        .with_tmpfs("/home")
    )
    backend = BubblewrapBackend("/usr/bin/bwrap")
    cmd = backend.compile(spec)

    tmpfs_home_idx = cmd.index("/home")
    project_idx = cmd.index("/home/user/project")
    # tmpfs /home must appear before /home/user/project
    assert tmpfs_home_idx < project_idx
