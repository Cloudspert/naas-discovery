"""CapacityProvider interface (§8) -- the pluggable capacity/telemetry seam.

The ranking logic (app/recommend/strategies.py) only ever talks to "a
CapacityProvider" and doesn't know or care which implementation is behind
it -- same reasoning as naas-api's AUTH_MODULES registry.
"""

from abc import ABC, abstractmethod
from typing import Optional

from app.models.clusters import ClusterEntry


class CapacityProvider(ABC):
    @abstractmethod
    async def get_headroom(self, cluster: ClusterEntry) -> Optional[float]:
        """Return the cluster's available headroom, or None if it couldn't
        be determined (unreachable backend, no query configured for this
        cluster, malformed response, ...). The caller (recommend/) decides
        what None means via CLUSTER_TELEMETRY_FAILURE_POLICY (§7).

        The number itself is opaque to naas-discovery -- whatever the
        configured query returns (bytes free, a percentage, anything) is
        compared as-is against CLUSTER_CAPACITY_THRESHOLD.
        """
        raise NotImplementedError
