import pytest

from app.health.cache import HealthCache
from app.registry.base import RegistrySource
from tests.fakes import FakeHealthChecker, make_cluster


class _StaticRegistry(RegistrySource):
    def __init__(self, clusters):
        self._clusters = clusters

    def list_clusters(self):
        return self._clusters


@pytest.mark.asyncio
async def test_start_populates_cache_before_returning():
    clusters = [make_cluster("A"), make_cluster("B")]
    registry = _StaticRegistry(clusters)
    checker = FakeHealthChecker(healthy_ids={"A"})
    cache = HealthCache(checker, registry, interval_seconds=999)

    await cache.start()

    assert cache.is_healthy("A") is True
    assert cache.is_healthy("B") is False

    await cache.stop()


@pytest.mark.asyncio
async def test_never_checked_cluster_reads_as_unhealthy_and_status_unknown():
    registry = _StaticRegistry([])
    checker = FakeHealthChecker(healthy_ids=set())
    cache = HealthCache(checker, registry, interval_seconds=999)

    assert cache.is_healthy("never-checked") is False
    assert cache.last_known_status("never-checked") is None


@pytest.mark.asyncio
async def test_disabled_clusters_are_not_polled():
    clusters = [make_cluster("A", enabled=False)]
    registry = _StaticRegistry(clusters)
    checker = FakeHealthChecker(healthy_ids={"A"})
    cache = HealthCache(checker, registry, interval_seconds=999)

    await cache.start()

    # Never polled -> "unconfirmed", which reads as unhealthy, even though
    # the fake checker would have said True.
    assert cache.is_healthy("A") is False
    assert cache.last_known_status("A") is None

    await cache.stop()
