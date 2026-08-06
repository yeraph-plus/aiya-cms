"""A2 management contract smoke checks (no database connection required)."""

from fastapi.testclient import TestClient

from inc.api.app import create_app
from inc.kernel.config import Settings


def test_a2_management_paths_are_exposed() -> None:
    application = create_app(Settings(_env_file=None, env="test", cache_backend="memory"))
    paths = application.openapi()["paths"]
    expected = {
        "/api/v1/dashboard",
        "/api/v1/content-types",
        "/api/v1/users",
        "/api/v1/users/{user_id}/roles",
        "/api/v1/comments/moderation",
        "/api/v1/audit-logs/{log_id}",
        "/api/v1/settings",
        "/api/v1/settings/{group_slug}",
        "/api/v1/public/settings",
        "/api/v1/auth/forgot-password",
        "/api/v1/auth/reset-password",
        "/api/v1/interactions/content/{content_id}/like",
        "/api/v1/interactions/content/{content_id}/rating",
        "/api/v1/me/interactions",
        "/api/v1/tasks",
        "/api/v1/tasks/{task_id}",
    }
    assert expected.issubset(paths)
    assert "/api/v1/settings/definitions" not in paths
    assert "/api/v1/settings/site-profile" not in paths

    patch_schema = paths["/api/v1/settings/{group_slug}"]["patch"]["requestBody"]["content"][
        "application/json"
    ]["schema"]["$ref"]
    assert patch_schema.endswith("/SettingPatch")


def test_content_state_actions_follow_declarative_route_contract() -> None:
    application = create_app(Settings(_env_file=None, env="test", cache_backend="memory"))
    paths = application.openapi()["paths"]
    assert "/api/v1/contents/{type_name}/{content_id}/{action}" in paths
    for action in ("archive", "unarchive", "restore"):
        assert f"/api/v1/contents/{{type_name}}/{{content_id}}/{action}" not in paths


def test_a2_taxonomy_paths_identify_type_name_like_content() -> None:
    application = create_app(Settings(_env_file=None, env="test", cache_backend="memory"))
    paths = application.openapi()["paths"]

    assert "/api/v1/terms/{type_name}" in paths
    assert "/api/v1/terms/{type_name}/{term_id}" in paths
    assert "/api/v1/terms" not in paths
    assert "/api/v1/terms/{term_id}" not in paths

    list_parameters = paths["/api/v1/terms/{type_name}"]["get"]["parameters"]
    assert {parameter["name"] for parameter in list_parameters if parameter["in"] == "path"} == {
        "type_name"
    }


def test_a2_taxonomy_request_dtos_do_not_duplicate_url_type_name() -> None:
    application = create_app(Settings(_env_file=None, env="test", cache_backend="memory"))
    schemas = application.openapi()["components"]["schemas"]

    assert "content_type" not in schemas["TermCreate"]["properties"]
    list_parameters = application.openapi()["paths"]["/api/v1/terms/{type_name}"]["get"][
        "parameters"
    ]
    assert "content_type" not in {parameter["name"] for parameter in list_parameters}


def test_unified_list_query_contract_is_exposed_in_openapi() -> None:
    application = create_app(Settings(_env_file=None, env="test", cache_backend="memory"))
    openapi = application.openapi()

    expected = {
        "/api/v1/contents/{type_name}": {"page", "size", "q", "status", "sort", "order"},
        "/api/v1/terms/{type_name}": {"page", "size", "q", "group", "slug", "sort", "order"},
        "/api/v1/comments": {"page", "size", "q", "sort", "order"},
        "/api/v1/comments/moderation": {"page", "size", "q", "status", "sort", "order"},
        "/api/v1/users": {"page", "size", "q", "status", "sort", "order"},
    }
    for path, names in expected.items():
        parameters = openapi["paths"][path]["get"]["parameters"]
        query_names = {item["name"] for item in parameters if item["in"] == "query"}
        assert names <= query_names

    terms_response = openapi["paths"]["/api/v1/terms/{type_name}"]["get"]["responses"]["200"]
    assert "Page_TermRead_" in terms_response["content"]["application/json"]["schema"]["$ref"]


def test_unknown_taxonomy_type_is_a_registered_not_found_error() -> None:
    application = create_app(Settings(_env_file=None, env="test", cache_backend="memory"))
    with TestClient(application, raise_server_exceptions=False) as client:
        response = client.get("/api/v1/terms/unknown")

    assert response.status_code == 404
    assert response.json()["code"] == "TERM_005"
