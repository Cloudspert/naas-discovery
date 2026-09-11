# naas-discovery — Cluster Discovery API

A FastAPI service, **deployed once, centrally** (unlike its sibling
[naas-api](../naas-api), which runs once per cluster). It holds a registry
of every cluster in the fleet and answers one question through one
endpoint: *given some criteria, what clusters match, and which one should
be used?*

> Full rationale and every design decision behind this service lives in
> [docs/design/naas-discovery-design.md](docs/design/naas-discovery-design.md).
> Read that first if you're wondering *why* something works the way it
> does — this README is the *what*, that doc is the *why*.

## Endpoints

| Method | Path                       | Description                                                              |
|--------|----------------------------|---------------------------------------------------------------------------|
| `GET`  | `/api/v1/clusters`         | List every matching, healthy cluster, with one flagged `recommended`.     |
| `GET`  | `/api/v1/clusters/{id}`    | A single cluster by id, regardless of health (includes a `healthy` field).|
| `GET`  | `/healthz`, `/readyz`      | naas-discovery's own liveness/readiness probes.                           |
| `GET`  | `/docs`                    | Swagger UI (Authorize button wired to Basic Auth).                        |

All `/api/v1` endpoints require HTTP Basic auth.

### Examples

```bash
# Every cluster
curl -u admin:changeme http://localhost:8080/api/v1/clusters

# Filtered -- also picks a recommendation among the matches
curl -u admin:changeme "http://localhost:8080/api/v1/clusters?region=eu-west-1&environment=dev"

# Filter by an arbitrary label
curl -u admin:changeme "http://localhost:8080/api/v1/clusters?labels.team=payments"

# One cluster by id
curl -u admin:changeme http://localhost:8080/api/v1/clusters/CAS-ELE-001
```

```json
{
  "recommended_cluster_id": "CAS-DEV-001",
  "count": 2,
  "items": [
    { "id": "CAS-DEV-001", "endpoint": "https://naas-api.cas-dev-001.example.com", "recommended": true, "...": "..." },
    { "id": "CAS-DEV-002", "endpoint": "https://naas-api.cas-dev-002.example.com", "recommended": false, "...": "..." }
  ]
}
```

## Configuration

All via `CLUSTER_`-prefixed environment variables (see `app/core/config.py`).
Key ones:

| Variable | Default | Purpose |
|---|---|---|
| `CLUSTER_REGISTRY_PATH` | `/etc/naas-discovery/clusters.yaml` | The cluster registry file. |
| `CLUSTER_RECOMMENDATION_MODE` | `priority` | `priority` \| `metrics` \| `hybrid`. |
| `CLUSTER_RECOMMENDATION_PRECEDENCE` | `priority` | `priority` \| `telemetry` (only used when `mode=hybrid`). |
| `CLUSTER_CAPACITY_THRESHOLD` | unset | Headroom cutoff for the hybrid priority-gate. |
| `CLUSTER_TELEMETRY_MODULE` | `none` | `none` \| `prometheus` \| `native_api`. |
| `CLUSTER_TELEMETRY_CONFIG_PATH` | `/etc/naas-discovery/telemetry.yaml` | Prometheus URL + PromQL template (Secret-mounted). |
| `CLUSTER_TELEMETRY_FAILURE_POLICY` | `fail_open` | `fail_open` \| `fail_closed`. |
| `CLUSTER_HEALTH_MODULE` | `http` | `none` \| `http` — **on by default**. |
| `CLUSTER_HEALTH_CHECK_INTERVAL_SECONDS` | `30` | Background poll interval. |
| `CLUSTER_HEALTH_CHECK_TIMEOUT_SECONDS` | `3` | Per-cluster `/healthz` timeout. |
| `CLUSTER_AUTH_MODULE` | `basic` | Active auth module. |
| `CLUSTER_BASIC_AUTH_USERS` | `{}` | JSON map `{"user":"pass"}`. |
| `CLUSTER_BASIC_AUTH_USERS_FILE` | unset | YAML file alternative to the above, takes precedence when set. |

## Architecture

```
app/
  main.py            composition root + lifespan (starts the health cache)
  core/
    config.py          CLUSTER_*-prefixed settings
    errors.py
  models/
    clusters.py         request/response + internal registry schemas
  registry/            where cluster entries come from
    base.py              RegistrySource interface
    file_source.py       clusters.yaml-backed implementation
    matching.py          generic filter matching (region/environment/provider/labels)
  recommend/
    strategies.py        priority / metrics / hybrid ranking, tie-break
  telemetry/            pluggable capacity module
    base.py               CapacityProvider interface
    noop.py, prometheus.py, native_api.py
    config.py             telemetry.yaml loader + per-cluster override resolution
  health/                pluggable health-check module
    base.py               HealthChecker interface
    noop.py, http.py
    cache.py              background poller + in-memory status cache
  auth/                  vendored from naas-api, + file-based users
  api/
    deps.py, clusters.py
```

See [docs/DEVELOPER.md](docs/DEVELOPER.md) for a full walkthrough of every
module and the request flow.

## Local development

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt

export CLUSTER_REGISTRY_PATH=config/clusters.yaml
export CLUSTER_BASIC_AUTH_USERS='{"admin":"changeme"}'
# The fixture clusters in config/clusters.yaml don't run a real naas-api,
# so turn off health filtering locally or everything gets excluded:
export CLUSTER_HEALTH_MODULE=none

uvicorn app.main:app --reload --port 8080
```

Or with **Docker Compose** (no local Python needed):

```bash
docker compose up app          # run the API at localhost:8080
docker compose run --rm tests  # run the full test suite
```

## Tests

Unit tests exercise each module in isolation (fakes for the registry/
telemetry/health interfaces, `respx` for mocking outbound HTTP). Functional
tests drive the full HTTP stack via `TestClient`.

```bash
pip install -r requirements-dev.txt
pytest
```

- **Unit:** matching, recommendation ranking (every mode/precedence/failure-
  policy combination + the random tie-break), the Prometheus provider
  (template rendering, per-cluster overrides, auth, failure handling), the
  HTTP health checker + background cache, the registry file loader, auth
  (including the file-based users path).
- **Functional:** auth 401s, list/filter/get happy paths, empty results,
  label filtering, health-based exclusion, OpenAPI security advertisement.

## Build & deploy

```bash
docker build -t quay.io/your-org/naas-discovery:0.1.0 .
docker push quay.io/your-org/naas-discovery:0.1.0

helm upgrade --install naas-discovery ./helm/naas-discovery \
  -n naas-discovery --create-namespace \
  --set image.repository=quay.io/your-org/naas-discovery \
  --set image.tag=0.1.0 \
  --set-json 'registry.clusters=[{"id":"CAS-ELE-001","endpoint":"https://naas-api.cas-ele-001.example.com","region":"eu-west-1","environment":"prod","provider":"internal-a","priority":100}]' \
  --set-json 'auth.basicUsers={"admin":"a-strong-password"}'
```

### Exposing the service

Pick **at most one** (both disabled by default; enabling both fails the
chart render):

```bash
# OpenShift Route
helm upgrade ... --set route.enabled=true --set route.host=naas-discovery.apps.example.com

# Kubernetes Ingress
helm upgrade ... \
  --set ingress.enabled=true \
  --set ingress.className=nginx \
  --set ingress.host=naas-discovery.example.com
```

### Health-check egress

`CLUSTER_HEALTH_MODULE=http` is on by default, which means this service
makes outbound calls to every enabled cluster's naas-api `/healthz`. If
your namespace's default NetworkPolicy blocks egress, set
`networkPolicy.enabled=true` and configure `networkPolicy.egress` — see
`helm/naas-discovery/values.yaml`. This is currently an **open question**
(design doc §17) whether it's needed in your environment.

## Status

This is a fresh build from the design doc — not yet run against a real
fleet. Several design decisions are flagged as open questions (design doc
§17) or implementation notes ([docs/DEV_LOG.md](docs/DEV_LOG.md)) that are
worth reading before relying on this in production, in particular:

- the direction of `CLUSTER_CAPACITY_THRESHOLD` comparison (see DEV_LOG),
- whether `GET /api/v1/clusters`'s `enabled` semantics match what you expect,
- the actual PromQL query content (this repo ships the *mechanism*, not a
  working query for your Prometheus).
