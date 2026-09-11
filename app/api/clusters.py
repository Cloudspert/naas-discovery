"""GET /clusters and GET /clusters/{id} (§3) -- the one list+recommend
endpoint, and the plain single-cluster lookup. Deliberately no separate
/resolve endpoint -- see design doc §1.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.deps import get_health_cache, get_registry, get_settings_dep, get_telemetry, require_auth
from app.models.clusters import ClusterDetail, ClusterListItem, ClustersResponse, to_public
from app.recommend.strategies import recommend
from app.registry.matching import match_clusters

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["clusters"])

_LABEL_PREFIX = "labels."


def _parse_label_filters(request: Request) -> dict[str, str]:
    return {
        key[len(_LABEL_PREFIX):]: value
        for key, value in request.query_params.items()
        if key.startswith(_LABEL_PREFIX)
    }


@router.get("/clusters", response_model=ClustersResponse)
async def list_clusters(
    request: Request,
    region: Optional[str] = None,
    environment: Optional[str] = None,
    provider: Optional[str] = None,
    _principal=Depends(require_auth),
    registry=Depends(get_registry),
    health_cache=Depends(get_health_cache),
    telemetry=Depends(get_telemetry),
    settings=Depends(get_settings_dep),
):
    labels = _parse_label_filters(request)
    matched = match_clusters(
        registry.list_clusters(),
        region=region,
        environment=environment,
        provider=provider,
        labels=labels,
    )

    # §9: health filtering happens before ranking -- an unhealthy cluster
    # is absent from `items` entirely, not just deprioritized.
    candidates = [c for c in matched if health_cache.is_healthy(c.id)]

    ranked = await recommend(candidates, settings, telemetry)

    items = [
        ClusterListItem(**to_public(entry.cluster).model_dump(), recommended=entry.recommended)
        for entry in ranked
    ]
    recommended_id = ranked[0].cluster.id if ranked else None

    logger.info(
        "event=clusters_query_result recommended=%s candidates=%d region=%s environment=%s provider=%s labels=%s",
        recommended_id,
        len(items),
        region,
        environment,
        provider,
        labels or None,
    )

    return ClustersResponse(recommended_cluster_id=recommended_id, count=len(items), items=items)


@router.get("/clusters/{cluster_id}", response_model=ClusterDetail)
async def get_cluster(
    cluster_id: str,
    _principal=Depends(require_auth),
    registry=Depends(get_registry),
    health_cache=Depends(get_health_cache),
):
    for cluster in registry.list_clusters():
        if cluster.id == cluster_id:
            return ClusterDetail(
                **to_public(cluster).model_dump(),
                healthy=health_cache.last_known_status(cluster.id),
            )
    raise HTTPException(status_code=404, detail=f"cluster '{cluster_id}' not found")
