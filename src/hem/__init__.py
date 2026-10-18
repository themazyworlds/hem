"""
Hem • Pure-Python, type-safe Bubblewrap (bwrap) sandbox builder and container isolation library.
"""

from subprocess import CalledProcessError, CompletedProcess, TimeoutExpired

from hem.builder import (
    BubblewrapBuilder,
    async_run_command,
    run_command,
)
from hem.errors import (
    ResourceResolutionError,
    SandboxError,
    SandboxUnavailableError,
)
from hem.resources import (
    allows_network,
    apply_resources,
    requires_host_session,
)
from hem.sandbox import (
    Sandbox,
    async_run_sandboxed,
    create_sandbox,
    is_available,
    run_sandboxed,
    wrap_command,
)

__all__ = [
    "BubblewrapBuilder",
    "CalledProcessError",
    "CompletedProcess",
    "ResourceResolutionError",
    "Sandbox",
    "SandboxError",
    "SandboxUnavailableError",
    "TimeoutExpired",
    "allows_network",
    "apply_resources",
    "async_run_command",
    "async_run_sandboxed",
    "create_sandbox",
    "is_available",
    "requires_host_session",
    "run_command",
    "run_sandboxed",
    "wrap_command",
]
__version__ = "0.1.0"
