"""
Hem • Pure-Python, type-safe Bubblewrap (bwrap) sandbox builder and container isolation library.
"""

lazy from subprocess import CalledProcessError, CompletedProcess, TimeoutExpired

lazy from hem.api import Explanation, Sandbox, async_run, is_available, run
lazy from hem.backends import Backend, BubblewrapBackend, DryRunBackend
lazy from hem.compat import (
    BubblewrapBuilder,
    allows_network,
    apply_resources,
    async_run_command,
    async_run_sandboxed,
    create_sandbox,
    requires_host_session,
    run_command,
    run_sandboxed,
    wrap_command,
)
lazy from hem.errors import (
    BackendError,
    ProfileError,
    ResourceResolutionError,
    SandboxError,
    SandboxUnavailableError,
    UnknownResourceError,
)
lazy from hem.profiles import (
    Profile,
    ProfileContext,
    desktop_profile,
    minimal_profile,
    register_profile,
    resolve_profile,
    strict_profile,
)
lazy from hem.resources import (
    DBusSession,
    DBusSystem,
    Display,
    Env,
    Net,
    PathGrant,
    Resource,
    Socket,
    Sound,
    parse_resource,
    parse_resources,
    register_resource,
)
lazy from hem.runner import get_minimal_env
lazy from hem.spec import LimitSpec, Mount, MountKind, NamespaceSpec, SandboxSpec

__all__ = [
    # Backends
    "Backend",
    # Errors
    "BackendError",
    "BubblewrapBackend",
    # Legacy compat shims
    "BubblewrapBuilder",
    "CalledProcessError",
    "CompletedProcess",
    # Resources
    "DBusSession",
    "DBusSystem",
    "Display",
    "DryRunBackend",
    "Env",
    # Top-level API
    "Explanation",
    # Spec
    "LimitSpec",
    "Mount",
    "MountKind",
    "NamespaceSpec",
    "Net",
    "PathGrant",
    # Profiles
    "Profile",
    "ProfileContext",
    "ProfileError",
    "Resource",
    "ResourceResolutionError",
    "Sandbox",
    "SandboxError",
    "SandboxSpec",
    "SandboxUnavailableError",
    "Socket",
    "Sound",
    "TimeoutExpired",
    "UnknownResourceError",
    "allows_network",
    "apply_resources",
    "async_run",
    "async_run_command",
    "async_run_sandboxed",
    "create_sandbox",
    "desktop_profile",
    # Runner
    "get_minimal_env",
    "is_available",
    "minimal_profile",
    "parse_resource",
    "parse_resources",
    "register_profile",
    "register_resource",
    "requires_host_session",
    "resolve_profile",
    "run",
    "run_command",
    "run_sandboxed",
    "strict_profile",
    "wrap_command",
]
__version__ = "0.1.0"
