"""
Hem • Exception Definitions.
Strongly typed exceptions for sandbox discovery, configuration, and execution boundaries.
"""

from __future__ import annotations


class SandboxError(RuntimeError):
    """Base exception for all Hem sandbox errors."""


class SandboxUnavailableError(SandboxError):
    """Raised when bubblewrap (bwrap) sandbox is requested but unavailable on the host system."""

    def __init__(
        self,
        reason: str = "Bubblewrap ('bwrap') is not installed or operational on this system.",
        hint: str | None = "Install 'bubblewrap' (bwrap) or run in an environment with container namespace support.",
    ) -> None:
        self.reason = reason
        self.hint = hint
        self.message = f"Sandbox isolation unavailable: {reason}"
        super().__init__(f"{self.message} (Hint: {hint})" if hint else self.message)


class ResourceResolutionError(SandboxError):
    """Raised when a requested sandbox resource cannot be resolved or mounted."""


class UnknownResourceError(ResourceResolutionError):
    """Raised when an unknown resource token is parsed."""


class ProfileError(SandboxError):
    """Raised when an invalid or unknown profile is requested."""


class BackendError(SandboxError):
    """Raised when a sandbox backend fails to compile or enforce a specification."""
