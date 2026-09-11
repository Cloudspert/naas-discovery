"""Modular filter matching (§6).

Generic, open-ended matching against a cluster's fixed fields and its
`labels` bag -- adding a new fixed field or a new label key doesn't change
how existing filters work. Used by GET /clusters (§3.1).

Implementation note (flag for confirmation -- see docs/DEV_LOG.md): the
design doc lists `enabled` as one of §3.1's query params, but also says the
endpoint "always returns every enabled cluster that matches" without
qualification. Those two statements are in tension (this is design-doc
open question §17.1). This implementation takes the conservative reading:
disabled clusters are *never* returned, unconditionally -- there is no
caller-facing way to ask for them. `enabled` is therefore NOT exposed as a
matchable field here.
"""

from app.models.clusters import ClusterEntry


def match_clusters(
    clusters: list[ClusterEntry],
    *,
    region: str | None = None,
    environment: str | None = None,
    provider: str | None = None,
    labels: dict[str, str] | None = None,
) -> list[ClusterEntry]:
    labels = labels or {}

    def matches(cluster: ClusterEntry) -> bool:
        if not cluster.enabled:
            return False
        if region is not None and cluster.region != region:
            return False
        if environment is not None and cluster.environment != environment:
            return False
        if provider is not None and cluster.provider != provider:
            return False
        for key, value in labels.items():
            if cluster.labels.get(key) != value:
                return False
        return True

    return [c for c in clusters if matches(c)]
