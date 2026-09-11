import pytest

from app.core.errors import ConfigError
from app.registry.file_source import FileRegistrySource


def test_loads_valid_clusters(clusters_yaml):
    path = clusters_yaml(
        """
        clusters:
          - id: CAS-ELE-001
            endpoint: "https://a.example.com"
            region: eu-west-1
            environment: prod
            provider: internal-a
            priority: 100
        """
    )

    source = FileRegistrySource(path)
    clusters = source.list_clusters()

    assert len(clusters) == 1
    assert clusters[0].id == "CAS-ELE-001"
    assert clusters[0].enabled is True  # default


def test_missing_file_raises_config_error(tmp_path):
    with pytest.raises(ConfigError):
        FileRegistrySource(str(tmp_path / "does-not-exist.yaml"))


def test_duplicate_id_raises_config_error(clusters_yaml):
    path = clusters_yaml(
        """
        clusters:
          - id: CAS-ELE-001
            endpoint: "https://a.example.com"
            region: eu-west-1
            environment: prod
            provider: internal-a
          - id: CAS-ELE-001
            endpoint: "https://b.example.com"
            region: eu-west-1
            environment: prod
            provider: internal-a
        """
    )

    with pytest.raises(ConfigError, match="duplicate"):
        FileRegistrySource(path)


def test_missing_required_field_raises_config_error(clusters_yaml):
    path = clusters_yaml(
        """
        clusters:
          - id: CAS-ELE-001
            region: eu-west-1
        """
    )

    with pytest.raises(ConfigError):
        FileRegistrySource(path)


def test_missing_top_level_key_raises_config_error(clusters_yaml):
    path = clusters_yaml("not_clusters: []")

    with pytest.raises(ConfigError):
        FileRegistrySource(path)
