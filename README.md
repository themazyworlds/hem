# Hem

> Pure-Python, type-safe Bubblewrap (`bwrap`) sandbox builder and container isolation library.

Hem is a lightweight, zero-dependency library for building and executing unprivileged Linux container sandboxes using Bubblewrap (`bwrap`). It provides a fluent, type-safe builder interface to configure filesystem mounts, kernel namespace isolation, environment variables, and process lifecycle boundaries without fragile, error-prone string manipulation.

## Features

- **Zero Runtime Dependencies**: 100% pure Python standard library.
- **Fluent, Type-Safe API**: Chainable methods for all Bubblewrap primitives (`ro_bind`, `bind`, `dev_bind`, `tmpfs`, `dev`, `proc`, `symlink`, `dir`, `chdir`, etc.).
- **Kernel Namespace Isolation**: Selective or total namespace unsharing (`user`, `pid`, `net`, `ipc`, `uts`, `cgroup`) and deterministic `--die-with-parent` lifecycle control.
- **Composite Presets**: Quick assembly methods like `bind_system_base()`, `set_namespaces()`, and `bind_workspace()`.
- **Branching & Immutability**: `.copy()` builders to construct and fork sandbox variants cleanly.

## Installation

```bash
uv add hem
# or
pip install hem
```

Ensure `bwrap` (Bubblewrap) is installed on your Linux system:

```bash
# Arch Linux
sudo pacman -S bubblewrap

# Debian / Ubuntu
sudo apt install bubblewrap

# Fedora
sudo dnf install bubblewrap
```

## Quick Start

```python
from hem import BubblewrapBuilder

# Check if bwrap is available on the host system
if not BubblewrapBuilder.is_available():
    raise RuntimeError("bwrap is not installed")

# Build a sandbox command
cmd = (
    BubblewrapBuilder()
    .clearenv()
    .bind_system_base()
    .tmpfs("/tmp")
    .set_namespaces(allow_network=False)
    .bind_workspace("/path/to/project", writable=False)
    .setenv("HOME", "/tmp")
    .build(["python3", "script.py"])
)

# Output: ['/usr/bin/bwrap', '--clearenv', '--ro-bind', '/usr', '/usr', ..., 'python3', 'script.py']
```

## License

Apache-2.0
