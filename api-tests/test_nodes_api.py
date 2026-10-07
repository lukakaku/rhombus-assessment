"""API tests for Rhombus AI project nodes endpoint.

Source:
  Chrome DevTools Network -> GET
  https://api.rhombusai.com/api/dataset/analyzer/v2/projects/5289/nodes

Required local environment variables for the authenticated test:
  RHOMBUS_TOKEN     - token only, without the "Bearer " prefix
  RHOMBUS_ORG_ID    - value from the X-Org-Id request header

Do not commit real credentials.
"""

import os

import pytest
import requests


BASE_URL = "https://api.rhombusai.com"
PROJECT_ID = "5289"
NODES_URL = f"{BASE_URL}/api/dataset/analyzer/v2/projects/{PROJECT_ID}/nodes"


def _auth_headers():
    token = os.getenv("RHOMBUS_TOKEN")
    org_id = os.getenv("RHOMBUS_ORG_ID")

    if not token or not org_id:
        pytest.skip(
            "Set RHOMBUS_TOKEN and RHOMBUS_ORG_ID locally to run the authenticated API test."
        )

    return {
        "Authorization": f"Bearer {token}",
        "X-Org-Id": org_id,
        "Accept": "application/json",
    }


def test_nodes_authenticated_returns_project_nodes():
    """API-01: valid authentication returns the current project's node list."""
    response = requests.get(NODES_URL, headers=_auth_headers(), timeout=20)

    assert response.status_code == 200, (
        f"Expected 200, got {response.status_code}: {response.text[:300]}"
    )
    assert "application/json" in response.headers.get("Content-Type", "")

    body = response.json()
    assert isinstance(body, list), f"Expected a JSON list, got {type(body).__name__}"
    assert len(body) > 0, "Expected at least one project node"

    for node in body:
        assert isinstance(node, dict)
        assert {"id", "node_id", "name"}.issubset(node), (
            f"Node missing expected fields: {node}"
        )

    names = [str(node.get("name", "")) for node in body]
    assert any(name.startswith("input_") for name in names), (
        f"No input node found in names: {names}"
    )
    assert any(name.startswith("output_") for name in names), (
        f"No output node found in names: {names}"
    )


def test_nodes_without_authentication_is_rejected():
    """API-02: the same endpoint should reject a request with no credentials."""
    response = requests.get(
        NODES_URL,
        headers={"Accept": "application/json"},
        timeout=20,
        allow_redirects=False,
    )

    assert response.status_code in {401, 403}, (
        f"Expected 401/403 for no credentials, got "
        f"{response.status_code}: {response.text[:300]}"
    )


def test_nodes_with_invalid_token_is_rejected():
    """API-03: an invalid Bearer token should be rejected."""
    org_id = os.getenv("RHOMBUS_ORG_ID")

    headers = {
        "Authorization": "Bearer invalid-test-token",
        "Accept": "application/json",
    }
    if org_id:
        headers["X-Org-Id"] = org_id

    response = requests.get(
        NODES_URL,
        headers=headers,
        timeout=20,
        allow_redirects=False,
    )

    assert response.status_code in {401, 403}, (
        f"Expected 401/403 for invalid token, got "
        f"{response.status_code}: {response.text[:300]}"
    )
