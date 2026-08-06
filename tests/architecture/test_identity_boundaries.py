"""Architecture guards for the identity component (M1.5).

Contract source: context/kernel/identity.md §11, ADR-0017 §6.
"""

from pathlib import Path


def test_modules_never_import_identity_models() -> None:
    # modules may only consume UserRead/IdentityService via the identity public
    # API; touching the ORM models bypasses the DTO boundary (ADR-0003)
    modules_root = Path(__file__).parents[2] / "inc" / "modules"
    offenders: list[str] = []
    for path in modules_root.rglob("*.py"):
        content = path.read_text(encoding="utf-8")
        if "inc.kernel.identity.models" in content:
            offenders.append(str(path.relative_to(modules_root)))
    assert offenders == []


def test_identity_public_surface_does_not_export_orm_models() -> None:
    import inc.kernel.identity as identity

    for name in ("User", "Identity", "Organization", "UserRepository", "IdentityRepository"):
        assert not hasattr(identity, name), f"ORM symbol leaked through identity public API: {name}"


def test_identity_service_does_not_own_session_or_commit() -> None:
    service_path = Path(__file__).parents[2] / "inc" / "kernel" / "identity" / "service.py"
    source = service_path.read_text(encoding="utf-8")

    assert ".commit(" not in source
    assert "uow.session" not in source
