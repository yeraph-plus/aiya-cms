"""Four-layer import-direction guards.

Contract source: context/spec/architecture.md §3 (dependency matrix) and
context/spec/composition.md §4.

Rules enforced:

- kernel never imports capabilities, features, api, adapters or modules.
- a capability never imports a sibling capability, features, api, adapters or modules.
- a feature only touches the public surface of capabilities: definition,
  schemas, commands, queries, ports, activities, events and package roots.
- api never imports capability internals (models, repositories, uow, ...).
- the modules layer does not exist and nothing imports it.
"""

from __future__ import annotations

import re

from _graph import INC_ROOT, REPO_ROOT, first_party_imports, iter_source_files

UPPER_LAYERS = ("inc.capabilities.", "inc.features.", "inc.api.", "inc.modules.")

CAPABILITY_PUBLIC_SUBS = frozenset(
    {"", "definition", "schemas", "commands", "queries", "ports", "activities", "events"}
)
FEATURE_PUBLIC_SUBS = frozenset({"", "definition", "schemas", "api", "workflows"})
ADAPTER_PUBLIC_CAPABILITY_SUBS = frozenset(
    {"", "definition", "schemas", "commands", "queries", "ports", "activities", "events"}
)
API_CAPABILITY_SUBS = CAPABILITY_PUBLIC_SUBS | frozenset(
    {"api", "diagnostics", "metrics", "readmodels", "adapters"}
)


def _submodule(module: str, level: int) -> str:
    parts = module.split(".")
    return parts[level] if len(parts) > level else ""


def test_kernel_never_imports_upper_layers() -> None:
    offenders: list[str] = []
    for path in iter_source_files(INC_ROOT / "kernel"):
        for module in first_party_imports(path):
            if module.startswith(UPPER_LAYERS):
                offenders.append(f"{path}: imports {module}")
    assert offenders == []


def test_capabilities_never_import_siblings_or_upper_layers() -> None:
    capabilities_root = INC_ROOT / "capabilities"
    assert capabilities_root.is_dir(), "inc/capabilities skeleton missing"
    offenders: list[str] = []
    for path in iter_source_files(capabilities_root):
        own = path.relative_to(capabilities_root).parts[0]
        for module in first_party_imports(path):
            if module.startswith("inc.capabilities."):
                other = _submodule(module, 2)
                if other != own:
                    offenders.append(f"{path}: imports sibling capability {module}")
            elif module.startswith(("inc.features.", "inc.api.", "inc.adapters.", "inc.modules.")):
                offenders.append(f"{path}: imports forbidden layer {module}")
    assert offenders == []


def test_features_import_only_capability_public_surface() -> None:
    features_root = INC_ROOT / "features"
    assert features_root.is_dir(), "inc/features skeleton missing"
    offenders: list[str] = []
    for path in iter_source_files(features_root):
        for module in first_party_imports(path):
            if not module.startswith("inc.capabilities."):
                continue
            sub = _submodule(module, 3)
            if sub not in CAPABILITY_PUBLIC_SUBS:
                offenders.append(f"{path}: imports capability internals {module}")
    assert offenders == []


def test_api_never_imports_capability_internals() -> None:
    api_root = INC_ROOT / "api"
    assert api_root.is_dir(), "inc/api skeleton missing"
    offenders: list[str] = []
    for path in iter_source_files(api_root):
        for module in first_party_imports(path):
            if module.startswith("inc.capabilities."):
                sub = _submodule(module, 3)
                if sub not in API_CAPABILITY_SUBS:
                    offenders.append(f"{path}: imports capability internals {module}")
            elif module.startswith("inc.features."):
                sub = _submodule(module, 3)
                if sub not in FEATURE_PUBLIC_SUBS:
                    offenders.append(f"{path}: imports feature internals {module}")
            elif module.startswith("inc.modules."):
                offenders.append(f"{path}: imports modules layer {module}")
    assert offenders == []


def test_http_adapters_never_use_orm_or_sqlalchemy() -> None:
    """HTTP adapters map transport data to public commands/queries only."""

    offenders: list[str] = []
    for path in iter_source_files(INC_ROOT / "api" / "http"):
        source = path.read_text(encoding="utf-8")
        if (
            "sqlalchemy" in source
            or "uow.session" in source
            or "session.add" in source
            or ".models import" in source
        ):
            offenders.append(str(path))
    assert offenders == []


def test_adapters_use_only_public_capability_surfaces() -> None:
    adapters_root = INC_ROOT / "adapters"
    assert adapters_root.is_dir(), "inc/adapters skeleton missing"
    offenders: list[str] = []
    for path in iter_source_files(adapters_root):
        for module in first_party_imports(path):
            if module.startswith("inc.capabilities."):
                sub = _submodule(module, 3)
                if sub not in ADAPTER_PUBLIC_CAPABILITY_SUBS:
                    offenders.append(f"{path}: imports capability internals {module}")
            elif module.startswith("inc.api."):
                offenders.append(f"{path}: imports composition root {module}")
            elif module.startswith("inc.features."):
                sub = _submodule(module, 3)
                if sub not in FEATURE_PUBLIC_SUBS:
                    offenders.append(f"{path}: imports feature internals {module}")
    assert offenders == []


def test_auth_router_delegates_self_service_orchestration_to_feature() -> None:
    auth_source = (INC_ROOT / "api" / "http" / "routers_auth.py").read_text(encoding="utf-8")
    me_source = (INC_ROOT / "api" / "http" / "routers_me.py").read_text(encoding="utf-8")
    assert "services.me" in me_source
    assert "inc.features.check_in" not in auth_source
    assert "FinalizeAsset" not in me_source
    assert "_me_dto" not in me_source
    assert "RegisterLocalUser" not in auth_source
    assert "RequestPasswordReset" not in auth_source
    assert "AssignDefaultUserRole" not in auth_source


def test_modules_layer_is_removed_and_unreferenced() -> None:
    assert not (INC_ROOT / "modules").exists(), "inc/modules must not return"
    legacy_import = re.compile(r"(?:from|import) inc\.modules(?:\.[\w.]+)?")
    for root in (INC_ROOT, REPO_ROOT / "tests"):
        for path in iter_source_files(root):
            assert legacy_import.search(path.read_text(encoding="utf-8")) is None, path
