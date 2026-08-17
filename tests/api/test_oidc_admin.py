"""Administrator OIDC transport safety contracts."""

from inc.api.http.routers_oidc_admin import _map_error
from inc.capabilities.oidc_provider.schemas import OidcError


def test_oidc_command_errors_map_to_valid_kernel_codes() -> None:
    mapped = _map_error(OidcError("invalid_request", "protected client"))

    assert mapped.code == "oidc.client.invalid_request"
