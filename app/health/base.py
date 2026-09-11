"""HealthChecker interface (§9) -- a separate, independent concern from
telemetry (app/telemetry/): telemetry answers "how much room does this
cluster have", health answers "is this cluster even reachable".
"""

from abc import ABC, abstractmethod

from app.models.clusters import ClusterEntry


class HealthChecker(ABC):
    @abstractmethod
    async def check(self, cluster: ClusterEntry) -> bool:
        """Return True if the cluster is currently healthy.

        Anything that isn't a clean "yes" -- unreachable, timeout, non-2xx
        -- must return False. There is no third "unknown" outcome at this
        level; the cache (cache.py) treats "never successfully checked"
        the same way, per the design doc's "always excluded, no
        failure-policy setting" rule (§9).
        """
        raise NotImplementedError
