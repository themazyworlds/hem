"""
Unit tests for pure immutable SandboxSpec and Mount data structures.
"""



from hem.spec import Mount, MountKind, NamespaceSpec, SandboxSpec


def test_mount_dataclass():
    m = Mount("/etc", MountKind.RO, "/etc", try_ok=True)
    assert m.target == "/etc"
    assert m.kind == MountKind.RO
    assert m.try_ok is True


def test_namespace_spec():
    ns = NamespaceSpec()
    assert ns.unshare_user is True
    assert ns.unshare_pid is True
    assert ns.unshare_net is True
    assert ns.active_namespaces()["pid"] is True


def test_sandbox_spec_immutability():
    spec1 = SandboxSpec()
    spec2 = spec1.with_ro_mount("/usr")
    spec3 = spec2.with_env("FOO", "bar").with_namespaces(unshare_net=False)

    assert len(spec1.mounts) == 0
    assert len(spec2.mounts) == 1
    assert len(spec3.mounts) == 1
    assert spec3.namespaces.unshare_net is False
    assert spec2.namespaces.unshare_net is True
    assert spec3.env_map()["FOO"] == "bar"


def test_spec_without_env():
    spec = SandboxSpec().with_env("A", "1").with_env("B", "2")
    spec_unset = spec.without_env("A")
    assert "A" not in spec_unset.env_map()
    assert spec_unset.env_map()["B"] == "2"
    assert "A" in spec_unset.unset_env


def test_spec_as_dict():
    spec = (
        SandboxSpec()
        .with_ro_mount("/usr")
        .with_env("HELLO", "world")
        .with_cwd("/tmp")
    )
    d = spec.as_dict()
    assert isinstance(d, dict)
    assert d["cwd"] == "/tmp"
    assert d["env"]["HELLO"] == "world"
    assert d["clean_env"] is True
    assert len(d["mounts"]) == 1
