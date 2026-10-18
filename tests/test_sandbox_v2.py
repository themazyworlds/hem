"""
Unit tests for high-level hem.Sandbox API.
"""

from pathlib import Path

from hem import DBusSession, Sandbox


def test_sandbox_immutability_and_derive(tmp_path: Path):
    sb1 = Sandbox("strict", workspace=tmp_path)
    sb2 = sb1.allow("net")
    sb3 = sb2.allow(DBusSession())

    assert len(sb1.resources) == 0
    assert len(sb2.resources) == 1
    assert len(sb3.resources) == 2

    # Derived copy
    sb_derived = sb1.derive(workspace=tmp_path / "sub", writable=True)
    assert sb_derived.workspace == (tmp_path / "sub").resolve()
    assert sb_derived.writable is True
    assert sb1.writable is False


def test_sandbox_explain(tmp_path: Path):
    sb = Sandbox("strict", workspace=tmp_path).allow("net")
    explanation = sb.explain(["python", "main.py"])
    report = str(explanation)

    assert "backend" in report
    assert "network      allowed" in report
    assert "namespaces   unshared:" in report
    assert "filesystem" in report
    assert "environment" in report
    # Secrets must not be shown
    assert "values hidden" in report


def test_dry_run_execution():
    from hem.backends.dry_run import DryRunBackend

    sb = Sandbox("minimal", backend=DryRunBackend())
    cmd = sb.build(["echo", "hello"])
    assert cmd[0] == "dry-run"
    assert "hello" in cmd
