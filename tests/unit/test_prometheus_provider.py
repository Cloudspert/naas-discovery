import httpx
import pytest
import respx

from app.telemetry.config import TelemetryConfig, TelemetryOverride
from app.telemetry.prometheus import PrometheusCapacityProvider
from tests.fakes import make_cluster


def _success_response(value: float) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "status": "success",
            "data": {"resultType": "vector", "result": [{"metric": {}, "value": [1700000000, str(value)]}]},
        },
    )


@pytest.mark.asyncio
@respx.mock
async def test_renders_query_template_with_cluster_id():
    config = TelemetryConfig(
        prometheus_url="https://prom.example.com",
        capacity_query="available{cluster=\"{{ cluster_id }}\"}",
    )
    route = respx.get("https://prom.example.com/api/v1/query").mock(return_value=_success_response(42.0))

    provider = PrometheusCapacityProvider(config)
    headroom = await provider.get_headroom(make_cluster("CAS-ELE-001"))

    assert headroom == 42.0
    assert route.calls.last.request.url.params["query"] == 'available{cluster="CAS-ELE-001"}'


@pytest.mark.asyncio
@respx.mock
async def test_sends_basic_auth_when_username_configured():
    config = TelemetryConfig(
        prometheus_url="https://prom.example.com",
        capacity_query="up",
        username="reader",
        password="s3cret",
    )
    route = respx.get("https://prom.example.com/api/v1/query").mock(return_value=_success_response(1.0))

    provider = PrometheusCapacityProvider(config)
    await provider.get_headroom(make_cluster("CAS-ELE-001"))

    auth_header = route.calls.last.request.headers["authorization"]
    assert auth_header.startswith("Basic ")


@pytest.mark.asyncio
@respx.mock
async def test_no_auth_header_when_username_not_set():
    config = TelemetryConfig(prometheus_url="https://prom.example.com", capacity_query="up")
    route = respx.get("https://prom.example.com/api/v1/query").mock(return_value=_success_response(1.0))

    provider = PrometheusCapacityProvider(config)
    await provider.get_headroom(make_cluster("CAS-ELE-001"))

    assert "authorization" not in route.calls.last.request.headers


@pytest.mark.asyncio
async def test_returns_none_when_no_query_configured_for_cluster():
    config = TelemetryConfig()  # nothing set, no overrides

    provider = PrometheusCapacityProvider(config)
    headroom = await provider.get_headroom(make_cluster("CAS-ELE-001"))

    assert headroom is None


@pytest.mark.asyncio
@respx.mock
async def test_returns_none_on_unreachable_backend():
    config = TelemetryConfig(prometheus_url="https://prom.example.com", capacity_query="up")
    respx.get("https://prom.example.com/api/v1/query").mock(side_effect=httpx.ConnectError("boom"))

    provider = PrometheusCapacityProvider(config)
    assert await provider.get_headroom(make_cluster("CAS-ELE-001")) is None


@pytest.mark.asyncio
@respx.mock
async def test_returns_none_on_prometheus_error_status():
    config = TelemetryConfig(prometheus_url="https://prom.example.com", capacity_query="up")
    respx.get("https://prom.example.com/api/v1/query").mock(
        return_value=httpx.Response(200, json={"status": "error", "error": "bad query"})
    )

    provider = PrometheusCapacityProvider(config)
    assert await provider.get_headroom(make_cluster("CAS-ELE-001")) is None


@pytest.mark.asyncio
@respx.mock
async def test_returns_none_on_empty_result():
    config = TelemetryConfig(prometheus_url="https://prom.example.com", capacity_query="up")
    respx.get("https://prom.example.com/api/v1/query").mock(
        return_value=httpx.Response(200, json={"status": "success", "data": {"result": []}})
    )

    provider = PrometheusCapacityProvider(config)
    assert await provider.get_headroom(make_cluster("CAS-ELE-001")) is None


@pytest.mark.asyncio
@respx.mock
async def test_per_cluster_override_uses_its_own_url_and_query():
    config = TelemetryConfig(
        prometheus_url="https://default.example.com",
        capacity_query="default_query",
        overrides=[
            TelemetryOverride(
                name="CAS-DEV-*",
                prometheus_url="https://dev.example.com",
                capacity_query="dev_query",
            )
        ],
    )
    default_route = respx.get("https://default.example.com/api/v1/query").mock(
        return_value=_success_response(1.0)
    )
    dev_route = respx.get("https://dev.example.com/api/v1/query").mock(return_value=_success_response(2.0))

    provider = PrometheusCapacityProvider(config)

    ele_headroom = await provider.get_headroom(make_cluster("CAS-ELE-001"))
    dev_headroom = await provider.get_headroom(make_cluster("CAS-DEV-001"))

    assert ele_headroom == 1.0 and default_route.called
    assert dev_headroom == 2.0 and dev_route.called
