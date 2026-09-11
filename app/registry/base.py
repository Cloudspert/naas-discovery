"""RegistrySource interface (§4) -- where cluster entries come from.

clusters.yaml (file_source.py) is the first implementation. Swapping to a
database or another API later means writing a new RegistrySource, not
touching the API routes, the matching engine (§6), or the recommendation
logic (§7).
"""

from abc import ABC, abstractmethod

from app.models.clusters import ClusterEntry


class RegistrySource(ABC):
    @abstractmethod
    def list_clusters(self) -> list[ClusterEntry]:
        """Return every cluster in the registry, in no particular order."""
        raise NotImplementedError
