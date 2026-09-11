"""Hand-written fakes for unit tests -- same approach as naas-api's own
tests/fakes.py: no mocking library for these, just simple in-memory
implementations of the interfaces.
"""

from typing import Optional

from app.health.base import HealthChecker
from app.models.clusters import ClusterEntry
from app.telemetry.base import CapacityProvider


def make_cluster(
    cluster_id: str,
    *,
    priority: int = 0,
    region: str = "eu-west-1",
    environment: str = "dev",
    provider: str = "internal-a",
    enabled: bool = True,
    labels: Optional[dict[str, str]] = None,
    endpoint: Optional[str] = None,
) -> ClusterEntry:
    return ClusterEntry(
        id=cluster_id,
        endpoint=endpoint or f"https://{cluster_id.lower()}.example.com",
        region=region,
        environment=environment,
        provider=provider,
        enabled=enabled,
        priority=priority,
        labels=labels or {},
    )


class FakeCapacityProvider(CapacityProvider):
    """Returns whatever headroom value was configured for each cluster id;
    a missing entry means "couldn't be determined" (None), same as a real
    provider's failure case.
    """

    def __init__(self, headrooms: dict[str, Optional[float]]):
        self._headrooms = headrooms

    async def get_headroom(self, cluster: ClusterEntry) -> Optional[float]:
        return self._headrooms.get(cluster.id)


class FakeHealthChecker(HealthChecker):
    def __init__(self, healthy_ids: set[str]):
        self._healthy_ids = healthy_ids

    async def check(self, cluster: ClusterEntry) -> bool:
        return cluster.id in self._healthy_ids
