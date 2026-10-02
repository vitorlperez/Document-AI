from uuid import uuid4

import pytest

from app.organizations.models import Membership, MembershipRole
from tests.api.test_access_admin import admin_api  # noqa: F401
from tests.api.test_text_search_api import search_api  # noqa: F401


def test_mcp_info_reports_unconfigured_server_without_guessing_url(admin_api):  # noqa: F811
    client, _factory, org = admin_api
    settings = client.app.state.settings
    settings.mcp_resource_url = settings.mcp_issuer_url = settings.mcp_jwks_url = None
    response = client.get(f"/organizations/{org}/mcp-info")
    assert response.status_code == 200
    assert response.json() == {
        "configured": False, "resource_url": None, "issuer_url": None,
        "transport": "streamable-http", "static_key_enabled": False,
        "tools": ["search", "fetch", "list_sources"],
    }


@pytest.mark.parametrize("static_keys", [False, True])
def test_mcp_info_uses_runtime_configuration_and_excludes_private_settings(admin_api, static_keys):  # noqa: F811
    client, _factory, org = admin_api
    settings = client.app.state.settings
    settings.mcp_resource_url = "https://mcp.example.test/custom/mcp"
    settings.mcp_issuer_url = "https://auth.example.test"
    settings.mcp_jwks_url = "https://auth.example.test/private/jwks"
    settings.mcp_static_key_enabled = static_keys
    response = client.get(f"/organizations/{org}/mcp-info")
    assert response.status_code == 200
    info = response.json()
    assert info["configured"] is True
    assert info["resource_url"] == settings.mcp_resource_url
    assert info["issuer_url"] == settings.mcp_issuer_url
    assert info["static_key_enabled"] is static_keys
    assert "jwks" not in response.text
    settings.mcp_jwks_url = None
    assert client.get(f"/organizations/{org}/mcp-info").json()["configured"] is False


def test_mcp_info_requires_admin_membership_and_session(admin_api):  # noqa: F811
    client, factory, org = admin_api
    assert client.get(f"/organizations/{uuid4()}/mcp-info").status_code == 403
    with factory.begin() as session:
        session.query(Membership).filter_by(organization_id=org).update({"role": MembershipRole.MEMBER})
    assert client.get(f"/organizations/{org}/mcp-info").status_code == 403
    client.cookies.clear()
    assert client.get(f"/organizations/{org}/mcp-info").status_code == 401
