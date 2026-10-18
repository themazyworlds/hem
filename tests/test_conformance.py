"""
Hem • Security Conformance Test Suite.
Validates the core security guarantees of the sandbox using live container execution.
"""

import os
import sys
from pathlib import Path

import pytest

import hem
from hem import DBusSession, Net, Sandbox


@pytest.fixture(autouse=True)
def require_bwrap():
    if not hem.is_available():
        pytest.skip("Bubblewrap ('bwrap') is not operational on this host.")


def test_conformance_secret_isolation(tmp_path: Path):
    """
    Host secrets present in the host environment must NOT be visible inside the container
    either via the container's environment or via /proc/1/environ (bwrap process environment).
    """
    secret_marker = "SUPER_SECRET_TOKEN_XYZ_123"
    totp_marker = "TOTP_CREDENTIAL_KEY_999"

    host_env = dict(os.environ)
    host_env["MY_SECRET_VAR"] = secret_marker
    host_env["TEXTILE_TOTP_SECRET"] = totp_marker

    probe_code = f"""
import os, sys

# 1. Check container env
for k, v in os.environ.items():
    if "{secret_marker}" in v or "{totp_marker}" in v:
        print("LEAK_CONTAINER_ENV:" + k)

# 2. Check /proc/1/environ
try:
    with open("/proc/1/environ", "rb") as f:
        data = f.read()
        if b"{secret_marker.encode()}" in data:
            print("LEAK_PROC_1_SECRET")
        if b"{totp_marker.encode()}" in data:
            print("LEAK_PROC_1_TOTP")
except Exception:
    pass

print("CONFORMANCE_SECRETS_OK")
"""
    sb = Sandbox("strict", workspace=tmp_path, env=host_env)
    res = sb.run([sys.executable, "-c", probe_code], capture_output=True, text=True)

    assert res.returncode == 0
    assert "LEAK_CONTAINER_ENV" not in res.stdout
    assert "LEAK_PROC_1_SECRET" not in res.stdout
    assert "LEAK_PROC_1_TOTP" not in res.stdout
    assert "CONFORMANCE_SECRETS_OK" in res.stdout


def test_conformance_network_isolation(tmp_path: Path):
    """
    By default, network namespace must be unshared (only 'lo' interface present).
    When Net() resource is granted, network access is permitted.
    """
    probe_code = """
import socket, sys
try:
    # Check if any external connection can be opened
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(("8.8.8.8", 53))
    s.close()
    print("NETWORK_ACCESSIBLE")
except Exception:
    print("NETWORK_ISOLATED")
"""
    # 1. Strict sandbox: network isolated
    sb_isolated = Sandbox("strict", workspace=tmp_path)
    res_isolated = sb_isolated.run([sys.executable, "-c", probe_code], capture_output=True, text=True)
    assert res_isolated.returncode == 0
    assert "NETWORK_ISOLATED" in res_isolated.stdout

    # 2. Network allowed sandbox
    sb_net = Sandbox("strict", workspace=tmp_path).allow(Net())
    assert sb_net.build_spec().namespaces.unshare_net is False


def test_conformance_pid_isolation(tmp_path: Path):
    """
    PID namespace must be unshared. Sandboxed process must only see container processes,
    never host processes, even when using desktop profile or session resources.
    """
    probe_code = """
import os
pids = [int(p) for p in os.listdir("/proc") if p.isdigit()]
# A sandboxed container typically has bwrap (PID 1) and python (PID 2)
if len(pids) > 10:
    print(f"LEAK_HOST_PIDS:{len(pids)}")
else:
    print(f"PID_ISOLATED:{len(pids)}")
"""
    sb = Sandbox("desktop", workspace=tmp_path)
    res = sb.run([sys.executable, "-c", probe_code], capture_output=True, text=True)
    assert res.returncode == 0
    assert "LEAK_HOST_PIDS" not in res.stdout
    assert "PID_ISOLATED" in res.stdout


def test_conformance_workspace_read_only(tmp_path: Path):
    """
    Workspace must be read-only by default. Writing to workspace must fail.
    Only when writable=True should modifications succeed.
    """
    test_file = tmp_path / "test.txt"
    test_file.write_text("initial", encoding="utf-8")

    write_code = f"""
import sys
try:
    with open("{test_file}", "w") as f:
        f.write("modified")
    print("WRITE_SUCCESS")
except OSError as e:
    print(f"WRITE_FAILED:{{type(e).__name__}}")
"""
    # 1. Read-only default
    sb_ro = Sandbox("strict", workspace=tmp_path, writable=False)
    res_ro = sb_ro.run([sys.executable, "-c", write_code], capture_output=True, text=True)
    assert res_ro.returncode == 0
    assert "WRITE_FAILED:OSError" in res_ro.stdout or "WRITE_FAILED:PermissionError" in res_ro.stdout

    # 2. Writable
    sb_rw = Sandbox("strict", workspace=tmp_path, writable=True)
    res_rw = sb_rw.run([sys.executable, "-c", write_code], capture_output=True, text=True)
    assert res_rw.returncode == 0
    assert "WRITE_SUCCESS" in res_rw.stdout


def test_conformance_home_hidden(tmp_path: Path):
    """
    User home directory must be hidden under an empty tmpfs.
    """
    real_home_file = Path.home() / ".bashrc"
    if not real_home_file.exists():
        pytest.skip("No ~/.bashrc to test home isolation")

    probe_code = """
from pathlib import Path
home = Path.home()
bashrc = home / ".bashrc"
if bashrc.exists():
    print("LEAK_REAL_HOME")
else:
    print("HOME_HIDDEN")
"""
    sb = Sandbox("strict", workspace=tmp_path)
    res = sb.run([sys.executable, "-c", probe_code], capture_output=True, text=True)
    assert res.returncode == 0
    assert "LEAK_REAL_HOME" not in res.stdout
    assert "HOME_HIDDEN" in res.stdout


def test_conformance_dbus_session_socket_only(tmp_path: Path):
    """
    DBusSession resource must mount ONLY the D-Bus socket, never the surrounding runtime directory.
    """
    # Create mock runtime directory outside the sandbox workspace
    runtime_dir = tmp_path.parent / f"fake_runtime_{os.getpid()}"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    bus_sock = runtime_dir / "bus"
    bus_sock.touch()
    other_sensitive_sock = runtime_dir / "sensitive_agent.sock"
    other_sensitive_sock.touch()

    env = {
        "XDG_RUNTIME_DIR": str(runtime_dir),
        "DBUS_SESSION_BUS_ADDRESS": f"unix:path={bus_sock}",
    }

    probe_code = f"""
from pathlib import Path
bus = Path("{bus_sock}")
sensitive = Path("{other_sensitive_sock}")

bus_exists = bus.exists()
sensitive_exists = sensitive.exists()

print(f"BUS_EXISTS:{{bus_exists}}")
print(f"SENSITIVE_EXISTS:{{sensitive_exists}}")
"""
    sb = Sandbox("strict", workspace=tmp_path, env=env).allow(DBusSession())
    res = sb.run([sys.executable, "-c", probe_code], capture_output=True, text=True)
    assert res.returncode == 0
    assert "BUS_EXISTS:True" in res.stdout
    assert "SENSITIVE_EXISTS:False" in res.stdout
