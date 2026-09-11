from unittest.mock import patch

import pytest

from app.core.config import Settings
from app.recommend.strategies import recommend
from tests.fakes import FakeCapacityProvider, make_cluster


def _settings(**overrides) -> Settings:
    return Settings(**overrides)


@pytest.mark.asyncio
async def test_priority_mode_picks_highest_priority():
    clusters = [make_cluster("A", priority=50), make_cluster("B", priority=100)]
    settings = _settings(recommendation_mode="priority")
    telemetry = FakeCapacityProvider({})

    ranked = await recommend(clusters, settings, telemetry)

    assert ranked[0].cluster.id == "B"
    assert ranked[0].recommended is True
    assert [r.recommended for r in ranked[1:]] == [False]


@pytest.mark.asyncio
async def test_metrics_mode_picks_highest_headroom():
    clusters = [make_cluster("A", priority=100), make_cluster("B", priority=1)]
    settings = _settings(recommendation_mode="metrics")
    telemetry = FakeCapacityProvider({"A": 10.0, "B": 90.0})

    ranked = await recommend(clusters, settings, telemetry)

    # B has far less priority but far more headroom -- metrics mode is
    # telemetry-authoritative, so B should win.
    assert ranked[0].cluster.id == "B"


@pytest.mark.asyncio
async def test_metrics_mode_uses_priority_as_tiebreak_for_equal_headroom():
    clusters = [make_cluster("A", priority=1), make_cluster("B", priority=100)]
    settings = _settings(recommendation_mode="metrics")
    telemetry = FakeCapacityProvider({"A": 50.0, "B": 50.0})

    ranked = await recommend(clusters, settings, telemetry)

    assert ranked[0].cluster.id == "B"


@pytest.mark.asyncio
async def test_metrics_mode_fail_open_deprioritizes_missing_telemetry_but_keeps_cluster():
    clusters = [make_cluster("A", priority=1), make_cluster("B", priority=100)]
    settings = _settings(recommendation_mode="metrics", telemetry_failure_policy="fail_open")
    # A has real headroom, B's telemetry lookup failed (missing entry).
    telemetry = FakeCapacityProvider({"A": 1.0})

    ranked = await recommend(clusters, settings, telemetry)

    assert [r.cluster.id for r in ranked] == ["A", "B"]


@pytest.mark.asyncio
async def test_metrics_mode_fail_closed_excludes_missing_telemetry():
    clusters = [make_cluster("A", priority=1), make_cluster("B", priority=100)]
    settings = _settings(recommendation_mode="metrics", telemetry_failure_policy="fail_closed")
    telemetry = FakeCapacityProvider({"A": 1.0})

    ranked = await recommend(clusters, settings, telemetry)

    assert [r.cluster.id for r in ranked] == ["A"]


@pytest.mark.asyncio
async def test_metrics_mode_all_telemetry_missing_falls_back_to_priority():
    clusters = [make_cluster("A", priority=1), make_cluster("B", priority=100)]
    settings = _settings(recommendation_mode="metrics", telemetry_failure_policy="fail_open")
    telemetry = FakeCapacityProvider({})

    ranked = await recommend(clusters, settings, telemetry)

    assert ranked[0].cluster.id == "B"


@pytest.mark.asyncio
async def test_hybrid_priority_precedence_gates_clusters_under_threshold():
    clusters = [make_cluster("A", priority=100), make_cluster("B", priority=1)]
    settings = _settings(
        recommendation_mode="hybrid",
        recommendation_precedence="priority",
        capacity_threshold=10.0,
    )
    # A has the highest priority but not enough headroom -- should be gated out.
    telemetry = FakeCapacityProvider({"A": 5.0, "B": 50.0})

    ranked = await recommend(clusters, settings, telemetry)

    assert [r.cluster.id for r in ranked] == ["B"]


@pytest.mark.asyncio
async def test_hybrid_priority_precedence_without_threshold_falls_back_to_priority():
    clusters = [make_cluster("A", priority=1), make_cluster("B", priority=100)]
    settings = _settings(
        recommendation_mode="hybrid", recommendation_precedence="priority", capacity_threshold=None
    )
    telemetry = FakeCapacityProvider({"A": 999.0, "B": 0.0})

    ranked = await recommend(clusters, settings, telemetry)

    assert ranked[0].cluster.id == "B"


@pytest.mark.asyncio
async def test_hybrid_telemetry_precedence_behaves_like_metrics_mode():
    clusters = [make_cluster("A", priority=100), make_cluster("B", priority=1)]
    settings = _settings(recommendation_mode="hybrid", recommendation_precedence="telemetry")
    telemetry = FakeCapacityProvider({"A": 1.0, "B": 99.0})

    ranked = await recommend(clusters, settings, telemetry)

    assert ranked[0].cluster.id == "B"


@pytest.mark.asyncio
async def test_tie_break_picks_randomly_among_equally_ranked_clusters():
    clusters = [make_cluster("A", priority=50), make_cluster("B", priority=50), make_cluster("C", priority=1)]
    settings = _settings(recommendation_mode="priority")
    telemetry = FakeCapacityProvider({})

    with patch("app.recommend.strategies.random.choice") as fake_choice:
        fake_choice.side_effect = lambda pool: pool[0]
        ranked = await recommend(clusters, settings, telemetry)

    tied_ids = {c.id for c in fake_choice.call_args.args[0]}
    assert tied_ids == {"A", "B"}
    assert ranked[0].cluster.id == "A"


@pytest.mark.asyncio
async def test_empty_candidates_returns_empty_list():
    settings = _settings(recommendation_mode="priority")
    telemetry = FakeCapacityProvider({})

    assert await recommend([], settings, telemetry) == []
