import httpx
import pytest
import respx

from app.health.http import HttpHealthChecker
from app.health.noop import NoopHealthChecker
from tests.fakes import make_cluster


@pytest.mark.asyncio
async def test_noop_checker_always_reports_healthy():
    checker = NoopHealthChecker()
    cluster = make_cluster("A")

    assert await checker.check(cluster) is True


@pytest.mark.asyncio
@respx.mock
async def test_http_checker_true_on_2xx():
    cluster = make_cluster("A", endpoint="https://a.example.com")
    respx.get("https://a.example.com/healthz").mock(return_value=httpx.Response(200))

    checker = HttpHealthChecker(timeout_seconds=1)
    assert await checker.check(cluster) is True


@pytest.mark.asyncio
@respx.mock
async def test_http_checker_false_on_non_2xx():
    cluster = make_cluster("A", endpoint="https://a.example.com")
    respx.get("https://a.example.com/healthz").mock(return_value=httpx.Response(503))

    checker = HttpHealthChecker(timeout_seconds=1)
    assert await checker.check(cluster) is False


@pytest.mark.asyncio
@respx.mock
async def test_http_checker_false_on_connection_error():
    cluster = make_cluster("A", endpoint="https://a.example.com")
    respx.get("https://a.example.com/healthz").mock(side_effect=httpx.ConnectError("boom"))

    checker = HttpHealthChecker(timeout_seconds=1)
    assert await checker.check(cluster) is False


@pytest.mark.asyncio
@respx.mock
async def test_http_checker_uses_explicit_healthz_endpoint_when_set():
    cluster = make_cluster("A", endpoint="https://a.example.com")
    cluster = cluster.model_copy(update={"healthz_endpoint": "https://probe.a.example.com/live"})
    respx.get("https://probe.a.example.com/live").mock(return_value=httpx.Response(200))

    checker = HttpHealthChecker(timeout_seconds=1)
    assert await checker.check(cluster) is True
