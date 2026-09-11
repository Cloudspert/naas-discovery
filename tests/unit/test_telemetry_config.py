from app.telemetry.config import TelemetryConfig, TelemetryOverride, resolve_for_cluster


def test_no_overrides_uses_top_level_defaults():
    config = TelemetryConfig(prometheus_url="https://prom.example.com", capacity_query="up")

    resolved = resolve_for_cluster(config, "CAS-ELE-001")

    assert resolved.prometheus_url == "https://prom.example.com"
    assert resolved.capacity_query == "up"


def test_matching_override_wins_over_default():
    config = TelemetryConfig(
        prometheus_url="https://prom.example.com",
        capacity_query="default_query",
        overrides=[TelemetryOverride(name="CAS-DEV-*", prometheus_url="https://prom-dev.example.com")],
    )

    resolved = resolve_for_cluster(config, "CAS-DEV-002")

    assert resolved.prometheus_url == "https://prom-dev.example.com"
    # capacity_query wasn't set on the override -> falls back to the default.
    assert resolved.capacity_query == "default_query"


def test_exact_id_pattern_only_matches_that_id():
    config = TelemetryConfig(
        overrides=[TelemetryOverride(name="CAS-ELE-002", prometheus_url="https://only-002.example.com")]
    )

    assert resolve_for_cluster(config, "CAS-ELE-002").prometheus_url == "https://only-002.example.com"
    assert resolve_for_cluster(config, "CAS-ELE-003").prometheus_url is None


def test_first_matching_override_wins_when_several_match():
    config = TelemetryConfig(
        overrides=[
            TelemetryOverride(name="CAS-ELE-002", prometheus_url="https://exact.example.com"),
            TelemetryOverride(name="CAS-ELE-*", prometheus_url="https://wildcard.example.com"),
        ]
    )

    resolved = resolve_for_cluster(config, "CAS-ELE-002")

    assert resolved.prometheus_url == "https://exact.example.com"
