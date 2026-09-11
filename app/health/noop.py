"""The `none` health module (§9) -- every cluster is treated as healthy,
i.e. health-check filtering is effectively off.
"""

from app.models.clusters import ClusterEntry
from app.health.base import HealthChecker


class NoopHealthChecker(HealthChecker):
    async def check(self, cluster: ClusterEntry) -> bool:
        return True
