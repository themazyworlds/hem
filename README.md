# Hem

> Pure-Python, type-safe unprivileged container sandbox library for Linux.

Hem is a lightweight, zero-dependency library for building and executing unprivileged Linux container sandboxes. It strictly separates **what the sandbox should allow** (pure immutable data specifications) from **how the backend enforces it** (e.g. Bubblewrap).

## Features

- **Zero Runtime Dependencies**: 100% pure Python standard library (Python >= 3.11).
- **Pure Data Specification (`SandboxSpec`)**: Frozen, immutable dataclasses representing mounts, environment, and Linux namespaces that can be inspected, diffed, serialized, and tested on any platform without running container binaries.
- **Typed Resources**: Declarative grants (`Net`, `Display`, `DBusSession`, `DBusSystem`, `Sound`, `Socket`, `PathGrant`, `Env`) resolved against explicit environment dictionaries—never leaking arbitrary host secrets.
- **Composable Profiles**: Reusable policy presets (`minimal`, `strict`, `desktop`) with automated Python virtualenv and runtime path discovery.
- **Transparent Audit Reporting (`explain`)**: Built-in human-readable inspection breakdown showing all active mounts, namespace isolations, and environment keys (with secret values hidden).
- **Process Group Isolation**: Subprocess runner with process-group cleanup (`os.killpg`) ensuring all child workers are reaped on timeout.
- **100% Backwards Compatible**: Full compatibility shims (`BubblewrapBuilder`, `create_sandbox`, `run_sandboxed`) for existing workflows.

## Threat Model & Guarantees

### What Hem Protects Against
1. **Host Secret & Environment Leaking**: The sandbox launcher process is spawned with a sanitized minimal environment (`PATH`, `LANG`, `TERM`, `USER`, `HOME`). Host credentials, API tokens, and secrets present in the caller's environment are never visible inside the container or via `/proc/1/environ`.
2. **Filesystem Tampering**: Workspaces are read-only by default (`writable=False`). Host home directories and `/tmp` are shadowed with empty `tmpfs` instances.
3. **Network Exfiltration**: Network namespaces are unshared by default. Only the loopback interface (`lo`) exists unless network access (`Net()`) is explicitly granted.
4. **Process Tree & Signal Snooping**: The PID namespace is unshared by default. Sandboxed processes cannot inspect, signal, or trace host processes.
5. **IPC Over-privilege**: `DBusSession()` mounts only the session bus socket, never exposing surrounding runtime directories containing Wayland, audio, or agent sockets.

### What Hem Does Not Protect Against
- Kernel vulnerabilities or privilege escalations in the Linux kernel namespace subsystem.
- Denial of service via excessive CPU usage (unless managed by cgroups or external process supervisors).

## Installation

```bash
uv add hem
# or
pip install hem
```

Ensure `bwrap` (Bubblewrap) is installed on your Linux host:

```bash
# Arch Linux
sudo pacman -S bubblewrap

# Debian / Ubuntu
sudo apt install bubblewrap

# Fedora
sudo dnf install bubblewrap
```

## Quick Start

### 1. Instant One-Liner Execution
```python
import hem

# Run a sandboxed script with strict isolation and read-only workspace
res = hem.run(["python3", "task.py"], profile="strict", workspace="./project", timeout=30.0)
print(res.stdout)
```

### 2. Immutable, Branchable Sandbox
```python
import hem

# Create a desktop-capable base sandbox
base_box = hem.Sandbox(profile="desktop").allow(hem.Display(), hem.DBusSession())

# Derive a task-specific sandbox with network access and a writable workspace
task_box = base_box.allow(hem.Net()).derive(workspace="./build", writable=True)

# Inspect the sandbox policy
print(task_box.explain(["python3", "build.py"]))

# Execute
res = task_box.run(["python3", "build.py"], capture_output=True, text=True)
```

### 3. Pure Spec & Dry-Run Testing
```python
from hem import Sandbox
from hem.backends.dry_run import DryRunBackend

# Compile and audit a spec on any platform without needing bwrap installed
box = Sandbox("strict", backend=DryRunBackend())
cmd = box.build(["echo", "audited"])
```

## License

Apache-2.0
