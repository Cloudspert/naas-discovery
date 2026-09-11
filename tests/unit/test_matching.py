from app.registry.matching import match_clusters
from tests.fakes import make_cluster


def test_matches_on_region_environment_provider():
    clusters = [
        make_cluster("A", region="eu-west-1", environment="dev", provider="internal-a"),
        make_cluster("B", region="eu-west-1", environment="prod", provider="internal-a"),
        make_cluster("C", region="us-east-1", environment="dev", provider="internal-b"),
    ]

    result = match_clusters(clusters, region="eu-west-1", environment="dev")

    assert [c.id for c in result] == ["A"]


def test_matches_on_arbitrary_labels():
    clusters = [
        make_cluster("A", labels={"team": "payments"}),
        make_cluster("B", labels={"team": "platform"}),
    ]

    result = match_clusters(clusters, labels={"team": "payments"})

    assert [c.id for c in result] == ["A"]


def test_disabled_clusters_are_never_matched_regardless_of_filters():
    clusters = [make_cluster("A", enabled=False)]

    result = match_clusters(clusters)

    assert result == []


def test_no_filters_returns_every_enabled_cluster():
    clusters = [make_cluster("A"), make_cluster("B"), make_cluster("C", enabled=False)]

    result = match_clusters(clusters)

    assert {c.id for c in result} == {"A", "B"}
