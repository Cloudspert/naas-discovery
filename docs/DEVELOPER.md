# Developer guide

A code-level walkthrough of naas-discovery: every module, the request flow,
and the patterns used throughout. Read
[docs/design/naas-discovery-design.md](design/naas-discovery-design.md)
first for *why* the system is shaped this way — this document is the *how*.

For a log of implementation decisions made while building this (including
a couple of places where the design doc itself was ambiguous or, in one
case, internally inconsistent), see [DEV_LOG.md](DEV_LOG.md).

## Request flow: `GET /api/v1/clusters?environment=dev`

1. **`app/main.py`** routes the request to **`app/api/clusters.py:list_clusters`**.
2. **`require_auth`** (`app/api/deps.py`) authenticates via `app.state.auth`
   (a `BasicAuth` instance built at startup) — 401 with a `WWW-Authenticate`
   header on failure.
3. **`_parse_label_filters`** pulls any `labels.<key>=<value>` query params
   out of the raw query string (FastAPI can't declare these as typed
   params since the key names are open-ended).
4. **`match_clusters`** (`app/registry/matching.py`) filters
   `registry.list_clusters()` (everything loaded from `clusters.yaml` at
   startup) down to enabled clusters matching `region`/`environment`/
   `provider`/`labels`.
5. **Health filtering** happens right here in the route handler, not
   inside `match_clusters`: `[c for c in matched if health_cache.is_healthy(c.id)]`.
   `health_cache` (`app/health/cache.py`) is a background-polled in-memory
   map, not a live check — see "The health cache" below.
6. **`recommend`** (`app/recommend/strategies.py`) ranks the surviving
   candidates and flags exactly one `recommended`. This is where
   `telemetry.get_headroom()` gets called, if the configured mode needs it.
7. The ranked list is converted to `ClusterListItem`s and wrapped in a
   `ClustersResponse` (`app/models/clusters.py`).

`GET /api/v1/clusters/{id}` is much shorter: linear scan of
`registry.list_clusters()` for a matching id, 404 if none, otherwise a
`ClusterDetail` with `health_cache.last_known_status()` (which can be
`None`, unlike the list endpoint's binary in/out filtering).

## Module-by-module

### `app/core/config.py` — `Settings`

A `pydantic_settings.BaseSettings` subclass, `env_prefix="CLUSTER_"`. One
field per row in the design doc's §5 table. `Literal` types are used for
every enum-like setting (`recommendation_mode`, `telemetry_module`, ...) so
a typo in an env var fails at startup with a clear pydantic error instead
of silently falling through to unexpected behavior.

`get_settings()` is `@lru_cache`d — call it, don't construct `Settings()`
directly, in application code (tests are the exception: see "Testing"
below for why they must clear this cache between runs).

### `app/models/clusters.py`

- `ClusterEntry` — the full internal representation of one `clusters.yaml`
  row, including `priority` and `healthz_endpoint`, which are **never**
  serialized into an API response.
- `ClusterPublic` / `ClusterListItem` / `ClusterDetail` — what actually
  goes out over HTTP. `to_public()` converts one to the other.
- `ClusterEntry.healthz_url()` — the URL the health module hits: the
  explicit `healthz_endpoint` if set, else `{endpoint}/healthz`.

### `app/registry/`

- `base.py` — `RegistrySource` ABC, one method: `list_clusters()`.
- `file_source.py` — `FileRegistrySource`, the only implementation today.
  Loads and validates `clusters.yaml` **once**, at construction time (in
  `main.py`'s lifespan, so at process startup) — there is no hot-reload.
  Raises `ConfigError` (fail-fast, see `app/core/errors.py`) on a missing
  file, malformed YAML, a row that doesn't satisfy `ClusterEntry`, or a
  duplicate `id`.
- `matching.py` — `match_clusters()`, a plain function, not a class. Takes
  the full cluster list plus optional `region`/`environment`/`provider`/
  `labels` and returns the filtered subset. **Always** drops disabled
  clusters — see DEV_LOG for why `enabled` isn't a caller-facing filter.

### `app/recommend/strategies.py`

The one module worth reading slowly — see its module docstring for the
`capacity_threshold` direction issue (flagged in DEV_LOG) before touching
the gating logic.

`recommend()` dispatches on `settings.recommendation_mode`:

- `priority` → `_rank_by_priority`: sort by `ClusterEntry.priority`
  descending. No telemetry call at all.
- `metrics` → `_gather_headroom` (concurrent `asyncio.gather` over every
  candidate) then `_rank_by_metrics`: sort key is
  `(headroom or -inf, priority)`, so priority only breaks literal ties —
  including the "everyone's headroom is missing" case, which degrades
  cleanly to a pure-priority ordering.
- `hybrid` → same headroom gather, then either
  `_rank_hybrid_priority_gate` (`precedence=priority`, the default:
  priority orders, telemetry only excludes clusters under
  `capacity_threshold`) or `_rank_by_metrics` again (`precedence=telemetry`
  is defined to behave exactly like `metrics` mode).

Every ranking function returns `list[tuple[ClusterEntry, key]]` — carrying
the sort key alongside each cluster is what lets `_pick_recommended` find
every cluster tied for *first place* (not just look at index 0) and
`random.choice` among them. This is also why tests patch
`app.recommend.strategies.random.choice` rather than asserting on
statistical distribution across many runs — it's faster and it verifies
the *candidate set* passed to `random.choice`, not just the output.

### `app/telemetry/`

- `base.py` — `CapacityProvider` ABC: `get_headroom(cluster) -> float | None`.
  `None` always means "couldn't determine it" — the caller (recommend/)
  decides what that means via `telemetry_failure_policy`.
- `noop.py` — always `None`. The `none` module.
- `config.py` — `TelemetryConfig`/`TelemetryOverride` (pydantic models for
  `telemetry.yaml`) and `resolve_for_cluster()`, which walks `overrides`
  top-to-bottom with `fnmatch(cluster_id, override.name)` and returns the
  first match's fields, falling back field-by-field to the top-level
  config for anything the matching override didn't set.
- `prometheus.py` — `PrometheusCapacityProvider`. Renders
  `resolved.capacity_query` as a Jinja2 `Template` (context: `cluster_id`,
  `region`, `environment`, `provider`, `labels`), `GET`s
  `{prometheus_url}/api/v1/query?query=...` via the shared `httpx.AsyncClient`,
  and pulls `data.result[0].value[1]` out of the response
  (`_extract_scalar`). Every failure mode (connection error, non-2xx,
  unparseable JSON, empty result, wrong shape) returns `None` rather than
  raising — a bad Prometheus response should degrade the ranking, not crash
  the request.
- `native_api.py` — stub, raises `NotImplementedError` on construction.
  Phase 3 in the design doc; not built.
- `__init__.py` — `TELEMETRY_MODULES` name→factory dict + `build_telemetry()`,
  same registry pattern naas-api uses for `AUTH_MODULES`. Factories take
  `(settings, http_client)` — the client is shared and owned by `main.py`.

### `app/health/`

Structurally a near-mirror of `telemetry/`, but conceptually unrelated —
see the design doc §9 for why they're kept separate rather than merged
into one "cluster status" module.

- `base.py` — `HealthChecker` ABC: `check(cluster) -> bool`. No `None`
  outcome at this level (unlike `CapacityProvider`) — a checker either
  confirms healthy or it doesn't; "never confirmed" is represented one
  layer up, by absence from the cache.
- `noop.py` / `http.py` — `none` and `http` (default) implementations.
  `HttpHealthChecker` treats any `httpx.HTTPError` (timeout, connection
  refused, etc.) the same as a non-2xx response: `False`.
- `cache.py` — `HealthCache`. `start()` runs **one poll synchronously**
  before returning (so nothing reads as falsely-unhealthy at boot), then
  launches a background `asyncio.Task` that sleeps-then-polls in a loop.
  `is_healthy(id)` defaults to `False` for any id never successfully
  polled — this is the concrete mechanism behind "no failure-policy
  setting, unconfirmed is always excluded" from the design doc.
  `last_known_status(id)` is the `Optional[bool]` variant used by
  `GET /clusters/{id}`, which doesn't filter on health, just reports it.
- `__init__.py` — same registry pattern as telemetry's.

### `app/auth/`

`base.py` and `basic.py` are vendored from naas-api — `basic.py` verbatim,
`base.py` with one intentional change (the `WWW-Authenticate` realm string,
which would be actively wrong if left as `"naas-api"`). `__init__.py` adds
`_load_basic_auth_users()`, which is the only piece of the file-based-users
feature (`CLUSTER_BASIC_AUTH_USERS_FILE`) that exists anywhere — everything
downstream of it (`BasicAuth`) just receives a plain `dict`, identical to
naas-api's original.

### `app/api/`

`deps.py` — thin `Request → app.state.X` accessors plus `require_auth`,
same shape as naas-api's. `clusters.py` — the two routes, described above.

### `app/main.py`

The lifespan context manager is the entire composition root: build
`Settings`, one shared `httpx.AsyncClient`, `FileRegistrySource`,
`build_telemetry`, `build_health_checker` + `HealthCache`, `build_auth` —
all stashed on `app.state`, all torn down on shutdown (`health_cache.stop()`
then `http_client.aclose()`). `custom_openapi()` injects the active auth
module's security scheme into the schema and marks every `/api/v1/*`
operation as requiring it, so Swagger's Authorize button actually works —
`/healthz`/`/readyz`/`/docs` are deliberately left unauthenticated in the
schema.

## Extending the system

Adding a new pluggable implementation (say, a second `HealthChecker`)
means: write the class in `app/health/your_module.py` implementing the
ABC, add one line to `HEALTH_MODULES` in `app/health/__init__.py`, done —
`build_health_checker` and everything downstream of it doesn't change. The
same pattern applies to `app/telemetry/` and `app/auth/`.

## Testing

- `tests/fakes.py` — hand-written fakes (`FakeCapacityProvider`,
  `FakeHealthChecker`, `make_cluster`), no mocking library, matching
  naas-api's own approach.
- `respx` mocks `httpx` calls for anything that talks to a real service
  (Prometheus, a cluster's `/healthz`) — see `tests/unit/test_prometheus_provider.py`
  and `tests/unit/test_health_checker.py`.
- `tests/conftest.py`'s `_clear_settings_cache` autouse fixture is
  important: `get_settings()` is `@lru_cache`d in application code, so
  without clearing it, whichever test runs first would "freeze" `Settings`
  for the rest of the process. Functional tests that need different env
  vars use `monkeypatch.setenv` **before** entering `TestClient(app)`'s
  `with` block — the lifespan (and therefore `get_settings()`) only runs
  when that block is entered.
- Functional tests default `CLUSTER_HEALTH_MODULE=none` so most of them
  don't depend on real network calls; the two tests that specifically
  exercise health-based filtering turn it back on and mock the calls with
  `respx`.
