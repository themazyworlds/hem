"""
Hem • Sandbox Backend Protocol.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from hem.spec import SandboxSpec


@runtime_checkable
class Backend(Protocol):
    """Protocol for sandbox command compilers and enforcers."""

    name: str

    def is_available(self) -> bool:
        """Check if this execution backend is installed and operational on the host system."""
        ...

    def compile(self, spec: SandboxSpec, cmd: Sequence[str]) -> list[str]:
        """Compile an immutable SandboxSpec and target command into executable command tokens."""
        ...
