"""The `none` telemetry module (§8) -- ranking ignores capacity entirely."""

from typing import Optional

from app.models.clusters import ClusterEntry
from app.telemetry.base import CapacityProvider


class NoopCapacityProvider(CapacityProvider):
    async def get_headroom(self, cluster: ClusterEntry) -> Optional[float]:
        return None
