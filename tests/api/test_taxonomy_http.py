"""Taxonomy admin router tests.

Contract source: context/spec/http-openapi.md §5/§12,
context/spec/capabilities/taxonomy.md, features/post dimension declarations
(category single-select, tag multi-select, target type ``post``).
"""

from __future__ import annotations

import uuid
from typing import Any


async def _create_post(client: Any, headers: dict[str, str], title: str) -> str:
    created = await client.post(
        "/api/v1/admin/content",
        json={"type_name": "post", "title": title, "data": {}},
        headers=headers,
    )
    assert created.status_code == 200, created.text
    return created.json()["id"]


async def _register_user(uow_factory: Any, clock: Any, services: Any, username: str) -> Any:
    from inc.capabilities.identity.commands import (
        CommandContext as IdentityCommandContext,
    )
    from inc.capabilities.identity.commands import (
        RegisterLocalUser,
    )

    identity_ctx = IdentityCommandContext(
        uow_factory=uow_factory,
        clock=clock,
        hasher=services.hasher,
        outbox=services.outbox,
        audit_actor_id="system",
        audit_trace_id="test",
    )
    return await RegisterLocalUser(identity_ctx)(
        username=username,
        email=f"{username}@example.com",
        password="password-123456",
    )


async def test_dimensions_terms_and_assignment_flow(client: Any, admin_token: str) -> None:
    headers = {"Authorization": f"Bearer {admin_token}"}

    dims = await client.get("/api/v1/admin/taxonomy/dimensions", headers=headers)
    assert dims.status_code == 200, dims.text
    keys = {item["dimension_key"] for item in dims.json()}
    assert {"category", "tag"} <= keys

    term = await client.post(
        "/api/v1/admin/taxonomy/dimensions/tag/terms",
        json={"name": "Python", "slug": "python"},
        headers=headers,
    )
    assert term.status_code == 200, term.text
    term_id = term.json()["id"]
    assert term.json()["status"] == "active"

    unknown_dim = await client.post(
        "/api/v1/admin/taxonomy/dimensions/nope/terms",
        json={"name": "x", "slug": "x"},
        headers=headers,
    )
    assert unknown_dim.status_code == 422
    assert unknown_dim.json()["code"] == "taxonomy.unknown_dimension"

    renamed = await client.patch(
        f"/api/v1/admin/taxonomy/terms/{term_id}",
        json={"name": "Python 3"},
        headers=headers,
    )
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Python 3"

    terms = await client.get("/api/v1/admin/taxonomy/dimensions/tag/terms", headers=headers)
    assert terms.status_code == 200
    assert term_id in {item["id"] for item in terms.json()}

    # assign to a post: the post feature declares target type "post"
    post_id = await _create_post(client, headers, "tagged-post")
    assigned = await client.put(
        f"/api/v1/admin/taxonomy/targets/post/{post_id}/terms",
        json={"dimension_key": "tag", "term_ids": [term_id]},
        headers=headers,
    )
    assert assigned.status_code == 204, assigned.text

    fetched = await client.get(
        f"/api/v1/admin/taxonomy/targets/post/{post_id}/terms", headers=headers
    )
    assert fetched.status_code == 200, fetched.text
    assert [item["id"] for item in fetched.json()["tag"]] == [term_id]

    services = client.app.state.services
    current = await services.taxonomy_queries.get_target_terms("post", uuid.UUID(post_id))
    assert term_id in {item.id for item in current.get("tag", [])}

    # replace semantics: empty list clears the dimension's assignments
    cleared = await client.put(
        f"/api/v1/admin/taxonomy/targets/post/{post_id}/terms",
        json={"dimension_key": "tag", "term_ids": []},
        headers=headers,
    )
    assert cleared.status_code == 204
    current = await services.taxonomy_queries.get_target_terms("post", uuid.UUID(post_id))
    assert current.get("tag", []) == []

    # single-select category rejects two terms
    cat1 = await client.post(
        "/api/v1/admin/taxonomy/dimensions/category/terms",
        json={"name": "News", "slug": "news"},
        headers=headers,
    )
    cat2 = await client.post(
        "/api/v1/admin/taxonomy/dimensions/category/terms",
        json={"name": "Tech", "slug": "tech"},
        headers=headers,
    )
    too_many = await client.put(
        f"/api/v1/admin/taxonomy/targets/post/{post_id}/terms",
        json={"dimension_key": "category", "term_ids": [cat1.json()["id"], cat2.json()["id"]]},
        headers=headers,
    )
    assert too_many.status_code == 422
    assert too_many.json()["code"] == "taxonomy.too_many_terms"

    # missing target is a stable validation error
    missing = await client.put(
        f"/api/v1/admin/taxonomy/targets/post/{uuid.uuid4()}/terms",
        json={"dimension_key": "tag", "term_ids": [term_id]},
        headers=headers,
    )
    assert missing.status_code == 422
    assert missing.json()["code"] == "taxonomy.target_missing"

    # archived terms can no longer be assigned
    archived = await client.post(f"/api/v1/admin/taxonomy/terms/{term_id}/archive", headers=headers)
    assert archived.status_code == 200
    assert archived.json()["status"] == "archived"
    inactive = await client.put(
        f"/api/v1/admin/taxonomy/targets/post/{post_id}/terms",
        json={"dimension_key": "tag", "term_ids": [term_id]},
        headers=headers,
    )
    assert inactive.status_code == 422
    assert inactive.json()["code"] == "taxonomy.term_inactive"

    # remove every assignment of the target
    await client.put(
        f"/api/v1/admin/taxonomy/targets/post/{post_id}/terms",
        json={"dimension_key": "tag", "term_ids": [cat1.json()["id"]]},
        headers=headers,
    )
    removed = await client.delete(
        f"/api/v1/admin/taxonomy/targets/post/{post_id}/terms", headers=headers
    )
    assert removed.status_code == 204
    current = await services.taxonomy_queries.get_target_terms("post", uuid.UUID(post_id))
    assert all(not items for items in current.values())


async def test_taxonomy_routes_require_capability(
    client: Any, uow_factory: Any, clock: Any
) -> None:
    from tests.api.conftest import _mint_token_for

    services = client.app.state.services
    user = await _register_user(uow_factory, clock, services, "notaxo")
    token = await _mint_token_for(services, user.subject.id)
    headers = {"Authorization": f"Bearer {token}"}

    assert (
        await client.get("/api/v1/admin/taxonomy/dimensions", headers=headers)
    ).status_code == 403
    assert (
        await client.get(
            f"/api/v1/admin/taxonomy/targets/post/{uuid.uuid4()}/terms", headers=headers
        )
    ).status_code == 403
    assert (
        await client.post(
            "/api/v1/admin/taxonomy/dimensions/tag/terms",
            json={"name": "x", "slug": "x"},
            headers=headers,
        )
    ).status_code == 403
