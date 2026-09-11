"""YAML-file-backed RegistrySource (§2, §4)."""

from pathlib import Path

import yaml
from pydantic import ValidationError

from app.core.errors import ConfigError
from app.models.clusters import ClusterEntry
from app.registry.base import RegistrySource


class FileRegistrySource(RegistrySource):
    """Loads clusters.yaml once and keeps it in memory.

    The registry is a static config file (§2), not something naas-discovery
    writes to, so there's no live-reload here -- a config change means a
    restart, same as naas-api's own config.
    """

    def __init__(self, path: str):
        self._path = Path(path)
        self._clusters = self._load()

    def list_clusters(self) -> list[ClusterEntry]:
        return list(self._clusters)

    def _load(self) -> list[ClusterEntry]:
        if not self._path.exists():
            raise ConfigError(f"registry file not found: {self._path}")

        with self._path.open() as f:
            raw = yaml.safe_load(f) or {}

        raw_clusters = raw.get("clusters")
        if not isinstance(raw_clusters, list):
            raise ConfigError(f"{self._path}: expected a top-level 'clusters' list")

        clusters: list[ClusterEntry] = []
        seen_ids: set[str] = set()
        for i, item in enumerate(raw_clusters):
            try:
                cluster = ClusterEntry.model_validate(item)
            except ValidationError as exc:
                raise ConfigError(f"{self._path}: clusters[{i}] is invalid: {exc}") from exc

            if cluster.id in seen_ids:
                raise ConfigError(f"{self._path}: duplicate cluster id '{cluster.id}'")
            seen_ids.add(cluster.id)
            clusters.append(cluster)

        return clusters
