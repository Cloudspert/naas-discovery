"""PrometheusCapacityProvider (§8) -- queries a configured Prometheus using
a Jinja2-rendered PromQL template, per cluster (with optional per-cluster
overrides -- see app/telemetry/config.py).
"""

import logging
from typing import Optional

import httpx
from jinja2 import Template

from app.models.clusters import ClusterEntry
from app.telemetry.base import CapacityProvider
from app.telemetry.config import TelemetryConfig, resolve_for_cluster

logger = logging.getLogger(__name__)

# Not exposed as a setting yet -- the design doc doesn't define a
# telemetry-specific timeout. Flagged in docs/DEV_LOG.md as a candidate
# CLUSTER_PROMETHEUS_QUERY_TIMEOUT_SECONDS setting if this turns out to
# need tuning.
QUERY_TIMEOUT_SECONDS = 5.0


class PrometheusCapacityProvider(CapacityProvider):
    def __init__(self, config: TelemetryConfig, client: Optional[httpx.AsyncClient] = None):
        self._config = config
        # A shared client is injected in tests (respx) and in normal
        # operation (app.state) so connections get reused across calls.
        self._client = client or httpx.AsyncClient()

    async def get_headroom(self, cluster: ClusterEntry) -> Optional[float]:
        resolved = resolve_for_cluster(self._config, cluster.id)

        if not resolved.prometheus_url or not resolved.capacity_query:
            logger.warning("no Prometheus URL/query configured for cluster %s", cluster.id)
            return None

        query = Template(resolved.capacity_query).render(
            cluster_id=cluster.id,
            region=cluster.region,
            environment=cluster.environment,
            provider=cluster.provider,
            labels=cluster.labels,
        )

        auth = None
        if resolved.username is not None:
            auth = httpx.BasicAuth(resolved.username, resolved.password or "")

        url = resolved.prometheus_url.rstrip("/") + "/api/v1/query"

        try:
            response = await self._client.get(
                url, params={"query": query}, auth=auth, timeout=QUERY_TIMEOUT_SECONDS
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("Prometheus query failed for cluster %s: %s", cluster.id, exc)
            return None

        return _extract_scalar(payload, cluster.id)


def _extract_scalar(payload: dict, cluster_id: str) -> Optional[float]:
    """Pull the first sample's value out of a Prometheus instant-query
    response (https://prometheus.io/docs/prometheus/latest/querying/api/).
    """
    if payload.get("status") != "success":
        logger.warning("Prometheus query for cluster %s did not succeed: %s", cluster_id, payload)
        return None

    result = payload.get("data", {}).get("result", [])
    if not result:
        logger.warning("Prometheus query for cluster %s returned no series", cluster_id)
        return None

    try:
        return float(result[0]["value"][1])
    except (KeyError, IndexError, TypeError, ValueError):
        logger.warning("Prometheus query for cluster %s returned an unexpected shape", cluster_id)
        return None
