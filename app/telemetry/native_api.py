"""NativeAPICapacityProvider (§8) -- Phase 3, not yet implemented.

Design intent: for clusters whose own naas-api (or another in-cluster API)
already exposes usage/capacity directly, call that instead of Prometheus.
Left as a stub deliberately -- see docs/design/naas-discovery-design.md §8
and docs/DEV_LOG.md for what's still undecided before this can be built
(which endpoint, what shape).
"""

from typing import Optional

from app.models.clusters import ClusterEntry
from app.telemetry.base import CapacityProvider


class NativeAPICapacityProvider(CapacityProvider):
    def __init__(self):
        raise NotImplementedError(
            "native_api telemetry module is a Phase 3 design-doc item, not implemented yet"
        )

    async def get_headroom(self, cluster: ClusterEntry) -> Optional[float]:
        raise NotImplementedError
