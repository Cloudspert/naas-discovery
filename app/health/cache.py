"""Background health-poll cache (§9).

Checking every matching cluster's /healthz synchronously on every
GET /clusters call would add N network round-trips to every request, so
a background task polls periodically instead and GET /clusters just reads
the cache. Same "single worker per pod" caveat as naas-api's own
app/services/cache.py -- see the Dockerfile.
"""

import asyncio
import logging

from app.health.base import HealthChecker
from app.registry.base import RegistrySource

logger = logging.getLogger(__name__)


class HealthCache:
    def __init__(
        self,
        checker: HealthChecker,
        registry: RegistrySource,
        interval_seconds: int,
    ):
        self._checker = checker
        self._registry = registry
        self._interval_seconds = interval_seconds
        # A cluster with no entry here has never been successfully checked
        # -- is_healthy() treats that the same as an explicit False (§9:
        # "unconfirmed" and "unhealthy" are treated the same, always).
        self._status: dict[str, bool] = {}
        self._task: asyncio.Task | None = None

    def is_healthy(self, cluster_id: str) -> bool:
        return self._status.get(cluster_id, False)

    def last_known_status(self, cluster_id: str) -> bool | None:
        """For GET /clusters/{id} (§3.2), which shows health but doesn't
        filter on it -- None means "not checked yet", distinct from False.
        """
        return self._status.get(cluster_id)

    async def start(self) -> None:
        """Populate the cache with one synchronous poll before the app
        starts serving traffic, then keep refreshing in the background.
        Without the synchronous first poll, every cluster would read as
        unhealthy (and be excluded from GET /clusters) until the first
        background cycle completed.
        """
        if self._task is not None:
            return
        await self._poll_once()
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    async def _run_loop(self) -> None:
        while True:
            await asyncio.sleep(self._interval_seconds)
            await self._poll_once()

    async def _poll_once(self) -> None:
        clusters = [c for c in self._registry.list_clusters() if c.enabled]

        async def check_one(cluster):
            try:
                healthy = await self._checker.check(cluster)
            except Exception:
                logger.exception("unexpected error checking health of cluster %s", cluster.id)
                healthy = False
            self._status[cluster.id] = healthy
            logger.info("event=health_check_result cluster_id=%s healthy=%s", cluster.id, healthy)

        await asyncio.gather(*(check_one(c) for c in clusters))
