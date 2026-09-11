"""Pydantic models for the cluster registry and the public API (§2, §3)."""

from typing import Optional

from pydantic import BaseModel, Field


class ClusterEntry(BaseModel):
    """One entry from clusters.yaml (§2) -- the internal, full representation.

    `priority` and `healthz_endpoint` are used internally (ranking, health
    checks) and are NOT exposed through the public API -- see ClusterListItem
    / ClusterDetail below for what actually goes out over HTTP.
    """

    id: str
    endpoint: str
    healthz_endpoint: Optional[str] = None
    region: str
    environment: str
    provider: str
    enabled: bool = True
    priority: int = 0
    labels: dict[str, str] = Field(default_factory=dict)

    def healthz_url(self) -> str:
        """The URL §9's health checker should call for this cluster."""
        if self.healthz_endpoint:
            return self.healthz_endpoint
        return self.endpoint.rstrip("/") + "/healthz"


class ClusterPublic(BaseModel):
    """Fields common to every cluster shape the API returns."""

    id: str
    endpoint: str
    provider: str
    region: str
    environment: str
    enabled: bool
    labels: dict[str, str]


class ClusterListItem(ClusterPublic):
    """One entry in GET /clusters' `items` (§3.1)."""

    recommended: bool


class ClusterDetail(ClusterPublic):
    """The body of GET /clusters/{id} (§3.2) -- no `recommended`, has `healthy`."""

    healthy: Optional[bool] = None


class ClustersResponse(BaseModel):
    """The full body of GET /clusters (§3.1)."""

    recommended_cluster_id: Optional[str]
    count: int
    items: list[ClusterListItem]


def to_public(entry: ClusterEntry) -> ClusterPublic:
    return ClusterPublic(
        id=entry.id,
        endpoint=entry.endpoint,
        provider=entry.provider,
        region=entry.region,
        environment=entry.environment,
        enabled=entry.enabled,
        labels=entry.labels,
    )
