"""
Hem • High-Level Sandbox API (deprecated shim; use hem.Sandbox or hem.compat).
"""

from hem.api import Sandbox, async_run, is_available, run
from hem.compat import (
    async_run_sandboxed,
    create_sandbox,
    run_sandboxed,
    wrap_command,
)

__all__ = [
    "Sandbox",
    "async_run",
    "async_run_sandboxed",
    "create_sandbox",
    "is_available",
    "run",
    "run_sandboxed",
    "wrap_command",
]
