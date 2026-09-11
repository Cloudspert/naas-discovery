"""Recommendation ranking (§7): priority, telemetry, or both.

A cluster is gated out of the hybrid priority-precedence ranking when its
headroom is *below* CLUSTER_CAPACITY_THRESHOLD (not enough room) --
confirmed 2026-09-11, see docs/DEV_LOG.md. (An earlier draft of the design
doc said "over the threshold," which contradicted CapacityProvider being
documented as *available headroom*; the doc's wording was corrected to
match this implementation, not the other way around.)
"""

import asyncio
import random
from dataclasses import dataclass
from typing import Optional

from app.core.config import Settings
from app.models.clusters import ClusterEntry
from app.telemetry.base import CapacityProvider

NEGATIVE_INFINITY = float("-inf")


@dataclass
class RankedCluster:
    cluster: ClusterEntry
    recommended: bool


async def recommend(
    candidates: list[ClusterEntry],
    settings: Settings,
    telemetry: CapacityProvider,
) -> list[RankedCluster]:
    """Rank `candidates` (already filtered by app.registry.matching and
    already health-filtered by the caller) and flag exactly one as the
    recommendation. Returns them ordered, recommended first (§3.1).
    """
    if not candidates:
        return []

    if settings.recommendation_mode == "priority":
        ranked = _rank_by_priority(candidates)
    elif settings.recommendation_mode == "metrics":
        headrooms = await _gather_headroom(candidates, telemetry)
        ranked = _rank_by_metrics(candidates, headrooms, settings.telemetry_failure_policy)
    else:  # hybrid
        headrooms = await _gather_headroom(candidates, telemetry)
        if settings.recommendation_precedence == "priority":
            ranked = _rank_hybrid_priority_gate(
                candidates, headrooms, settings.capacity_threshold, settings.telemetry_failure_policy
            )
        else:
            ranked = _rank_by_metrics(candidates, headrooms, settings.telemetry_failure_policy)

    return _pick_recommended(ranked)


async def _gather_headroom(
    candidates: list[ClusterEntry], telemetry: CapacityProvider
) -> dict[str, Optional[float]]:
    results = await asyncio.gather(*(telemetry.get_headroom(c) for c in candidates))
    return {c.id: headroom for c, headroom in zip(candidates, results)}


def _rank_by_priority(candidates: list[ClusterEntry]) -> list[tuple[ClusterEntry, int]]:
    ranked = [(c, c.priority) for c in candidates]
    ranked.sort(key=lambda pair: pair[1], reverse=True)
    return ranked


def _rank_by_metrics(
    candidates: list[ClusterEntry],
    headrooms: dict[str, Optional[float]],
    failure_policy: str,
) -> list[tuple[ClusterEntry, tuple[float, int]]]:
    """Rank by headroom, `priority` as the tie-break for equal/missing
    telemetry (§7's `metrics` mode, and `hybrid` with precedence=telemetry).
    """
    eligible = candidates
    if failure_policy == "fail_closed":
        eligible = [c for c in candidates if headrooms.get(c.id) is not None]

    ranked = []
    for c in eligible:
        headroom = headrooms.get(c.id)
        # Missing headroom sorts last on the headroom axis -- if every
        # candidate is missing it (e.g. the whole Prometheus backend is
        # down), everyone ties at NEGATIVE_INFINITY and priority alone
        # decides, matching the design doc's documented fail_open case.
        key = (headroom if headroom is not None else NEGATIVE_INFINITY, c.priority)
        ranked.append((c, key))

    ranked.sort(key=lambda pair: pair[1], reverse=True)
    return ranked


def _rank_hybrid_priority_gate(
    candidates: list[ClusterEntry],
    headrooms: dict[str, Optional[float]],
    threshold: Optional[float],
    failure_policy: str,
) -> list[tuple[ClusterEntry, int]]:
    """priority orders the candidates; telemetry only gates eligibility
    (§7's default hybrid behavior: precedence=priority).
    """
    if threshold is None:
        # No threshold configured -- nothing to gate on, so this degrades
        # to plain priority ranking. Not explicitly specified in the
        # design doc; documented as a deliberate choice, see DEV_LOG.
        return _rank_by_priority(candidates)

    eligible = []
    for c in candidates:
        headroom = headrooms.get(c.id)
        if headroom is None:
            if failure_policy == "fail_closed":
                continue
            # fail_open: no capacity signal for this cluster -- don't gate
            # it out, let priority alone decide its fate.
            eligible.append(c)
            continue
        if headroom < threshold:
            continue  # not enough room -- see module docstring on direction
        eligible.append(c)

    return _rank_by_priority(eligible)


def _pick_recommended(ranked: list[tuple[ClusterEntry, object]]) -> list[RankedCluster]:
    """Random tie-break (§7): among clusters sharing the best rank, pick
    the recommendation at random, re-rolled every call. The rest keep
    their ranked order; the design doc doesn't require anything more
    specific there.
    """
    if not ranked:
        return []

    best_key = ranked[0][1]
    tied = [cluster for cluster, key in ranked if key == best_key]
    recommended = random.choice(tied)

    result = [RankedCluster(recommended, True)]
    result.extend(
        RankedCluster(cluster, False) for cluster, _ in ranked if cluster.id != recommended.id
    )
    return result
