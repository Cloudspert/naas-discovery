"""HttpHealthChecker (§9, default) -- GET on the cluster's healthz_url()."""

import logging

import httpx

from app.models.clusters import ClusterEntry
from app.health.base import HealthChecker

logger = logging.getLogger(__name__)


class HttpHealthChecker(HealthChecker):
    def __init__(self, timeout_seconds: float, client: httpx.AsyncClient | None = None):
        self._timeout_seconds = timeout_seconds
        self._client = client or httpx.AsyncClient()

    async def check(self, cluster: ClusterEntry) -> bool:
        try:
            response = await self._client.get(
                cluster.healthz_url(), timeout=self._timeout_seconds
            )
            return response.is_success
        except httpx.HTTPError as exc:
            logger.info("health check failed for cluster %s: %s", cluster.id, exc)
            return False
