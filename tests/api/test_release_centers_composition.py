from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from inc.api.archive_services import WorkArchiveCostBasis
from inc.api.config import ApiSettings
from inc.api.container import build_container
from inc.api.manifest import release
from inc.features.business_center import ArchiveFulfillment, QuoteClaims
from inc.kernel.errors import KernelError


def _codec(uow_factory: Any, clock: Any, tmp_path: Any, secret: str) -> Any:
    services = build_container(
        manifest=release,
        uow_factory=uow_factory,
        clock=clock,
        settings=ApiSettings(
            admin_session_secret=secret,
            oidc_signing_key_dir=str(tmp_path / secret[:8]),
        ),
    ).services
    assert services is not None and services.business_center is not None
    return services.business_center.token_codec


def test_quote_signing_key_is_stable_and_domain_derived(
    uow_factory: Any, clock: Any, tmp_path: Any
) -> None:
    claims = QuoteClaims(
        quote_id="quote-1",
        product_key="archive.download.manifest",
        product_version="1",
        pricing_policy_key="archive.files.fixed.v1",
        compensation_policy_version="1",
        amount=100,
        target_ref="published-work",
        target_digest="digest-1",
        parameters={},
        subject="subject-1",
        client_id="aiya-site",
        audience="aiya-admin",
        issued_at=clock.utc_now(),
        expires_at=clock.utc_now(),
        fulfillment=ArchiveFulfillment(
            target_ref="published-work",
            manifest_version="1",
            manifest_digest="digest-1",
            file_ids=("file-1",),
        ),
    )
    first = _codec(uow_factory, clock, tmp_path, "deployment-secret-one").encode(claims)
    second_codec = _codec(uow_factory, clock, tmp_path, "deployment-secret-one")
    other_codec = _codec(uow_factory, clock, tmp_path, "deployment-secret-two")

    assert second_codec.encode(claims) == first
    assert second_codec.decode(first) == claims
    with pytest.raises(KernelError, match="quote token is invalid"):
        other_codec.decode(first)


async def test_work_archive_cost_basis_preserves_slug_and_requires_manifest() -> None:
    class ContentQueries:
        def __init__(self, data: dict[str, Any]) -> None:
            self.data = data
            self.calls: list[dict[str, str]] = []

        async def get_published_by_slug(self, **kwargs: str) -> Any:
            self.calls.append(kwargs)
            return SimpleNamespace(id="content-id", data=self.data)

    content = ContentQueries(
        {
            "archive_manifest_version": "manifest-1",
            "download_files": [
                {
                    "archive_item_id": "item-1",
                    "version": 2,
                    "part_number": 1,
                    "size_bytes": 10,
                }
            ],
        }
    )
    basis = await WorkArchiveCostBasis(content).resolve(
        product=SimpleNamespace(), target_ref="published-work", parameters={}
    )
    assert content.calls == [{"type_name": "work", "slug": "published-work"}]
    assert basis.target_ref == "published-work"

    with pytest.raises(KernelError) as exc_info:
        await WorkArchiveCostBasis(ContentQueries({})).resolve(
            product=SimpleNamespace(), target_ref="missing-manifest", parameters={}
        )
    assert exc_info.value.code == "business_center.target_not_found"
