"""
Hem • Dry-Run Mock Backend.
Useful for testing, auditing, and running on systems without bubblewrap or Linux container privileges.
"""

from __future__ import annotations

import json
from collections.abc import Sequence

from hem.spec import SandboxSpec


class DryRunBackend:
    """Mock backend that compiles specs into an inspection representation without spawning bwrap."""

    name: str = "dry_run"

    def is_available(self) -> bool:
        """Always available on any platform."""
        return True

    def compile(self, spec: SandboxSpec, cmd: Sequence[str] = ()) -> list[str]:
        """Compile SandboxSpec into a dry-run token sequence."""
        spec_json = json.dumps(spec.as_dict(), sort_keys=True)
        return ["dry-run", f"--spec={spec_json}", "--", *(list(cmd) if cmd else [])]
