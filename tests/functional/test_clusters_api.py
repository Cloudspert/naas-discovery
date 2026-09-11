"""Functional tests -- full HTTP stack via TestClient, same approach as
naas-api's own functional tests. Most tests run with CLUSTER_HEALTH_MODULE
unset to `none` so they don't depend on real network calls; the dedicated
health-filtering test below turns it on and mocks the HTTP calls with respx.
"""

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.main import app

CLUSTERS_YAML = """
clusters:
  - id: CAS-ELE-001
    endpoint: "https://cas-ele-001.example.com"
    region: eu-west-1
    environment: prod
    provider: internal-a
    priority: 100
  - id: CAS-DEV-001
    endpoint: "https://cas-dev-001.example.com"
    region: eu-west-1
    environment: dev
    provider: internal-a
    priority: 100
    labels:
      team: payments
  - id: CAS-DEV-002
    endpoint: "https://cas-dev-002.example.com"
    region: eu-west-1
    environment: dev
    provider: internal-b
    priority: 50
"""


@pytest.fixture
def api_client(tmp_path, monkeypatch):
    registry_path = tmp_path / "clusters.yaml"
    registry_path.write_text(CLUSTERS_YAML)

    monkeypatch.setenv("CLUSTER_REGISTRY_PATH", str(registry_path))
    monkeypatch.setenv("CLUSTER_BASIC_AUTH_USERS", '{"admin": "changeme"}')
    monkeypatch.setenv("CLUSTER_HEALTH_MODULE", "none")

    with TestClient(app) as client:
        yield client


AUTH = ("admin", "changeme")


def test_requires_auth(api_client):
    response = api_client.get("/api/v1/clusters")
    assert response.status_code == 401
    assert "WWW-Authenticate" in response.headers


def test_wrong_credentials_rejected(api_client):
    response = api_client.get("/api/v1/clusters", auth=("admin", "wrong"))
    assert response.status_code == 401


def test_list_unfiltered_returns_every_enabled_cluster(api_client):
    response = api_client.get("/api/v1/clusters", auth=AUTH)

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 3
    assert body["recommended_cluster_id"] is not None


def test_list_filtered_to_multiple_matches_flags_one_recommended(api_client):
    response = api_client.get("/api/v1/clusters", params={"environment": "dev"}, auth=AUTH)

    body = response.json()
    assert body["count"] == 2
    assert body["recommended_cluster_id"] == "CAS-DEV-001"  # higher priority
    assert body["items"][0]["id"] == "CAS-DEV-001"
    assert body["items"][0]["recommended"] is True
    assert body["items"][1]["recommended"] is False


def test_list_filtered_to_one_match(api_client):
    response = api_client.get("/api/v1/clusters", params={"region": "eu-west-1", "environment": "prod"}, auth=AUTH)

    body = response.json()
    assert body["count"] == 1
    assert body["recommended_cluster_id"] == "CAS-ELE-001"


def test_list_filtered_to_zero_matches_returns_empty_not_404(api_client):
    response = api_client.get("/api/v1/clusters", params={"region": "does-not-exist"}, auth=AUTH)

    assert response.status_code == 200
    body = response.json()
    assert body == {"recommended_cluster_id": None, "count": 0, "items": []}


def test_list_filtered_by_label(api_client):
    response = api_client.get("/api/v1/clusters", params={"labels.team": "payments"}, auth=AUTH)

    body = response.json()
    assert body["count"] == 1
    assert body["items"][0]["id"] == "CAS-DEV-001"


def test_get_single_cluster(api_client):
    response = api_client.get("/api/v1/clusters/CAS-ELE-001", auth=AUTH)

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "CAS-ELE-001"
    assert "recommended" not in body
    assert "healthy" in body


def test_get_unknown_cluster_returns_404(api_client):
    response = api_client.get("/api/v1/clusters/does-not-exist", auth=AUTH)
    assert response.status_code == 404


def test_openapi_advertises_basic_auth_security(api_client):
    response = api_client.get("/openapi.json", auth=AUTH)

    schema = response.json()
    assert "basicAuth" in schema["components"]["securitySchemes"]
    clusters_get = schema["paths"]["/api/v1/clusters"]["get"]
    assert clusters_get["security"] == [{"basicAuth": []}]
    # /healthz should NOT require auth.
    assert "security" not in schema["paths"]["/healthz"]["get"]


def test_healthz_and_readyz_need_no_auth(api_client):
    assert api_client.get("/healthz").status_code == 200
    assert api_client.get("/readyz").status_code == 200


@respx.mock
def test_unhealthy_clusters_are_excluded_from_list(tmp_path, monkeypatch):
    registry_path = tmp_path / "clusters.yaml"
    registry_path.write_text(CLUSTERS_YAML)

    monkeypatch.setenv("CLUSTER_REGISTRY_PATH", str(registry_path))
    monkeypatch.setenv("CLUSTER_BASIC_AUTH_USERS", '{"admin": "changeme"}')
    monkeypatch.setenv("CLUSTER_HEALTH_MODULE", "http")

    respx.get("https://cas-ele-001.example.com/healthz").mock(return_value=httpx.Response(200))
    respx.get("https://cas-dev-001.example.com/healthz").mock(return_value=httpx.Response(503))
    respx.get("https://cas-dev-002.example.com/healthz").mock(return_value=httpx.Response(200))

    with TestClient(app) as client:
        response = client.get("/api/v1/clusters", params={"environment": "dev"}, auth=AUTH)

    body = response.json()
    assert body["count"] == 1
    assert body["items"][0]["id"] == "CAS-DEV-002"


@respx.mock
def test_get_single_cluster_shows_healthy_field_even_when_unhealthy(tmp_path, monkeypatch):
    registry_path = tmp_path / "clusters.yaml"
    registry_path.write_text(CLUSTERS_YAML)

    monkeypatch.setenv("CLUSTER_REGISTRY_PATH", str(registry_path))
    monkeypatch.setenv("CLUSTER_BASIC_AUTH_USERS", '{"admin": "changeme"}')
    monkeypatch.setenv("CLUSTER_HEALTH_MODULE", "http")

    respx.get("https://cas-ele-001.example.com/healthz").mock(return_value=httpx.Response(503))
    respx.get("https://cas-dev-001.example.com/healthz").mock(return_value=httpx.Response(200))
    respx.get("https://cas-dev-002.example.com/healthz").mock(return_value=httpx.Response(200))

    with TestClient(app) as client:
        response = client.get("/api/v1/clusters/CAS-ELE-001", auth=AUTH)

    assert response.status_code == 200
    assert response.json()["healthy"] is False
