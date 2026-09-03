# Design: naas-discovery — Cluster Discovery API

**Status:** Design only — not yet implemented. This document defines scope,
data model, and API shape; several details are explicitly deferred (see §17).
**Author:** platform-team
**Related:** [naas-api](../../../naas-api/README.md) (sibling project) —
specifically its [pluggable auth module](../../../naas-api/app/auth/) and
[Helm chart](../../../naas-api/helm/naas-api/), both mirrored here for
consistency.

---

## 1. Context & goal

**naas-api** ("Namespace as a Service") is deployed **once per cluster** and
provisions namespaces/quotas on the cluster it runs on. It does not know
anything about *other* clusters.

**naas-discovery** is a **single, centrally deployed** service — the opposite
shape. It holds a registry ("the dictionary") of every cluster in the fleet
(e.g. `CAS-ELE-001`) — its connection endpoint, region, environment, and
provider — and answers **one** question through **one** endpoint: *"given
these criteria (region, environment, and later arbitrary custom filters like
team), what clusters match, and which one should I use?"* There is
deliberately no separate "list" API and "resolve" API — a single
`GET /api/v1/clusters` call (§3.1) always returns every matching cluster
**and** flags one of them as the recommendation, so the caller never has to
round-trip through two endpoints to go from "what's out there" to "what do I
use." Calling it with no filters is just the degenerate case (the whole
registry, recommendation among all of it); calling it with filters is what
picks a specific cluster to hand to naas-api.

The caller is referred to below as **"opbox"** — whatever internal
tool/operator/orchestrator ends up consuming this API. Its exact identity
doesn't change the design, but see §17 for what it *would* change.

```
┌─────────┐   1. GET /clusters?region=..&environment=..   ┌──────────────────┐
│  opbox  │ ─────────────────────────────────────────────►│  naas-discovery   │
│         │ ◄───────────────────────────────────────────── │  (this project,   │
└─────────┘   { recommended_cluster_id, items: [...] }     │   one instance)   │
     │                                                     └──────────────────┘
     │ 2. call the recommended
     │    cluster's naas-api
     ▼
┌─────────────────────┐
│ naas-api on           │
│ CAS-ELE-001            │
│ (provisions namespace) │
└─────────────────────┘
```

Two **independent** background/optional lookups feed into step 1, kept
deliberately separate (§8 and §9 are not variants of one "status" system):

- **§8 (telemetry/capacity)** — an on-demand query to Prometheus or a
  cluster-native API, consulted only when ranking in `metrics`/`hybrid`
  mode. Off by default.
- **§9 (health)** — an independent background poll of every *enabled*
  cluster's own naas-api `/healthz` (the same naas-api instances shown
  above, not a separate system) — consulted on every `GET /clusters` call
  regardless of ranking mode, purely to decide inclusion/exclusion. On by
  default.

**Goals**
- **One** read/decision API over a cluster registry (the "dictionary"):
  filter criteria in → every matching cluster out, with one flagged as the
  recommendation (e.g. three `environment=dev` clusters all come back, with
  the one to actually use first in line — see §7). No second endpoint the
  caller has to know about or chain a call to.
- Modular filter matching so new inputs (team, custom labels) don't require
  touching the core matching engine.
- A pluggable capacity/telemetry module so the recommendation can *later*
  take cluster headroom into account, without that being a hard dependency
  now.
- A health-check module (**on by default**) so `GET /clusters` never
  recommends — or even lists — a cluster whose naas-api isn't currently
  reachable, avoiding failed provisioning attempts (§9).
- Reuse the same Basic Auth module naas-api already has, so both services
  authenticate identically.

**Non-goals (for now)**
- Writing to clusters, provisioning anything itself (that's naas-api's job).
- Being the source of truth for capacity — it *queries* capacity sources, it
  doesn't compute or store them.
- A UI or write/admin API for editing the registry — v1 registry is
  config-file-driven (see §4), not an admin CRUD API.

## 2. Data model — the cluster registry entry

Decisions already made: the registry is a **static YAML config file**
(not a database), `endpoint` means **the naas-api URL for that cluster**
(not the raw K8s/OpenShift API server), `environment` is a **single value
per cluster** (not a set of booleans), and `provider` is an **internal
designation** — not a cloud vendor (AWS/GCP/Azure/...). The exact taxonomy
of `provider` values is org-specific and not yet defined here — see §17.

```yaml
# config/clusters.yaml
clusters:
  - id: CAS-ELE-001                          # unique, human-assigned id
    endpoint: "https://naas-api.cas-ele-001.example.com"
    region: eu-west-1
    environment: prod                        # single value: dev | staging | prod | ...
    provider: internal-a                     # internal designation, NOT a cloud vendor (aws/gcp/azure) — taxonomy is org-specific, see §17
    enabled: true                            # eligibility toggle — see open question in §17
    priority: 100                            # admin-fixed recommendation weight — see §7
    labels: {}                               # open-ended bag for future filters, e.g. {team: payments}
```

`labels` is deliberately generic — matching the precedent already set in
naas-api's EgressIP design (labels are caller-owned key/value pairs, not
modeled concepts). This is how "team" and other future filters get added
**without a schema change**: a cluster gets `labels: {team: payments}`, and
the matching engine (§6) already knows how to match arbitrary label keys.

## 3. API

Base path `/api/v1`. All endpoints require auth (§10), same as naas-api.

### 3.1 List + recommend — `GET /api/v1/clusters`

The **one** endpoint for both "what matches" and "what should I use."
Query params (all optional, AND-combined): `region`, `environment`,
`provider`, `enabled`, plus **any `labels.<key>=<value>`** for the generic
bag (e.g. `labels.team=payments`). It always returns **every enabled
cluster that matches**, ordered so the first entry is the recommendation —
this is the shape needed for the multiple-dev-clusters case: three
`environment=dev` clusters all match, and the caller gets all three back in
one call, with the one to actually use listed first.

Health-check filtering (§9) is applied **before** results are returned:
when the health module is enabled (default), `items` never includes a
cluster the health module currently reports as unhealthy — it isn't just
deprioritized, it's absent entirely.

```
GET /api/v1/clusters?region=eu-west-1&environment=dev
```

```json
{
  "recommended_cluster_id": "CAS-DEV-002",
  "count": 3,
  "items": [
    {
      "id": "CAS-DEV-002",
      "endpoint": "https://naas-api.cas-dev-002.example.com",
      "provider": "internal-a",
      "region": "eu-west-1",
      "environment": "dev",
      "enabled": true,
      "labels": {},
      "recommended": true
    },
    {
      "id": "CAS-DEV-001",
      "endpoint": "https://naas-api.cas-dev-001.example.com",
      "provider": "internal-a",
      "region": "eu-west-1",
      "environment": "dev",
      "enabled": true,
      "labels": {},
      "recommended": false
    },
    {
      "id": "CAS-DEV-003",
      "endpoint": "https://naas-api.cas-dev-003.example.com",
      "provider": "internal-b",
      "region": "eu-west-1",
      "environment": "dev",
      "enabled": true,
      "labels": {},
      "recommended": false
    }
  ]
}
```

`items[0]` is always the recommendation — order carries the ranking.
`recommended_cluster_id` and each item's `recommended` flag are redundant
with that ordering; they're kept only so a caller reading a single field
instead of relying on array order still gets the right answer. **How the
ranking is computed — priority, telemetry, or a mix — is §7.**

- `200` with `items: []`, `count: 0`, `recommended_cluster_id: null` when
  nothing matches — ordinary list-endpoint semantics, not an error. This
  also covers the case where clusters matched the filters but every one of
  them is currently unhealthy (§9).
- Called with **no filters**, it's the whole enabled (and healthy) registry
  with a recommendation computed over *all* of it — not very meaningful
  across mixed environments/regions, but harmless; in practice callers
  filter by at least `environment` (and usually `region`).

`GET` + query params was chosen over a `POST` body for the same reason a
plain list endpoint would use it — trivial to `curl`/bookmark/cache; whether
a future filter set gets complex enough to need a `POST` body instead is an
open question (§17).

### 3.2 Get — `GET /api/v1/clusters/{id}`

Single registry entry, no recommendation logic involved and **not** subject
to §3.1's health filtering — a direct lookup by known id always returns the
entry regardless of current health, but includes a `healthy` field
reflecting the health module's last-known status (§9), so a caller asking
about one specific cluster can see it either way. `404` if `id` is unknown.

### 3.3 Operational

`GET /healthz`, `GET /readyz`, `GET /docs` (Swagger, Authorize button wired
to the active auth module) — identical convention to naas-api. This is
**naas-discovery's own** liveness/readiness — not to be confused with §9's
health module, which checks *other* clusters' naas-api instances.

## 4. Registry as a pluggable data source

Even though v1 reads `clusters.yaml` directly, the registry is accessed
through a small interface (a `RegistrySource` with a "list matching entries"
operation) rather than the API routes touching the file directly. `clusters.yaml`
is the **first implementation** of that interface. This is what lets the
registry move to a database or another API later (as flagged when the storage
decision was made) without changing §3's routes, §6's matching, or §7's
recommendation logic — only the source implementation changes.

## 5. Configuration additions

| Setting | Env var | Default | Purpose |
|---|---|---|---|
| `cluster_registry_path` | `APP_CLUSTER_REGISTRY_PATH` | `/etc/naas-discovery/clusters.yaml` | Path to §2's registry file (now also carries each cluster's `priority`) |
| `recommendation_mode` | `APP_RECOMMENDATION_MODE` | `priority` | `priority` \| `metrics` \| `hybrid` — see §7 |
| `recommendation_precedence` | `APP_RECOMMENDATION_PRECEDENCE` | `priority` | `priority` \| `telemetry` — only used when `recommendation_mode=hybrid`; which signal leads — see §7 |
| `capacity_threshold` | `APP_CAPACITY_THRESHOLD` | unset | Headroom cutoff used by §7's priority-precedence gate, once §8 is implemented |
| `telemetry_module` | `APP_TELEMETRY_MODULE` | `none` | `none` \| `prometheus` \| `native_api` — see §8 |
| `telemetry_failure_policy` | `APP_TELEMETRY_FAILURE_POLICY` | `fail_open` | `fail_open` \| `fail_closed` — behavior when the telemetry backend is unreachable during ranking, see §7 |
| `health_module` | `APP_HEALTH_MODULE` | `http` | `none` \| `http` — see §9 |
| `cluster_health_check_interval_seconds` | `APP_CLUSTER_HEALTH_CHECK_INTERVAL_SECONDS` | `30` | Background poll interval for §9's health cache |
| `health_check_timeout_seconds` | `APP_HEALTH_CHECK_TIMEOUT_SECONDS` | `3` | Per-cluster `/healthz` request timeout, see §9 |
| `auth_module` | `APP_AUTH_MODULE` | `basic` | Same as naas-api |
| `basic_auth_users` | `APP_BASIC_AUTH_USERS` | `{}` | Same as naas-api (JSON map, from env) |
| `basic_auth_users_file` | `APP_BASIC_AUTH_USERS_FILE` | unset | Path to a YAML file with the same `user: pass` map shape — a **file** alternative to `basic_auth_users`, see §10 |

Same `APP_`-prefixed, `pydantic-settings`-based pattern as naas-api's
`app/core/config.py`.

## 6. Modular filter matching

The matching engine used by §3.1's combined list/recommend endpoint (and,
trivially, §3.2's single-cluster get) takes an open-ended criteria map (`{region: ..., environment: ..., labels: {...}}`)
and matches it against each registry entry's fixed fields **and** its
`labels` bag generically. Adding a new fixed field (e.g. promoting `team`
out of `labels` into a first-class column someday) or a new query param is
additive — it doesn't change how existing filters work. This mirrors the
"caller owns the label, API doesn't model it" principle already used for
EgressIP filtering in naas-api.

## 7. Recommendation: priority, telemetry, or both

*(A standalone "advanced scheduling" section — a separate rules engine with
its own tie-break algorithm — was removed here for now. It's replaced by
the simpler mechanism below until there's a concrete need for more.)*

The use case driving this: multiple clusters can match the same filters —
most commonly several **dev** clusters in the same region. §3.1 already
returns all of them in one call; this section is about **how the first one
(the recommendation) gets picked**.

Two independent signals can drive the ranking:

- **Priority** — a fixed weight the administrator sets per cluster (the
  `priority` field added to `clusters.yaml` in §2, alongside identity —
  no separate scheduling file). Static, predictable, no runtime dependency.
- **Telemetry** — the capacity/headroom the §8 telemetry module reports for
  each matching cluster at request time. Dynamic, reflects real load, but
  depends on that module being configured and reachable.

### How they coexist: two config knobs

**Decided:** priority and telemetry are not blended into one number — each
gets a distinct role, so there's nothing to algorithmically "resolve" when
they disagree. Two settings control it:

- **`APP_RECOMMENDATION_MODE`** — `priority` \| `metrics` \| `hybrid`. Picks
  the overall strategy:
  - `priority` — rank by `priority` alone. Telemetry is never consulted,
    even if the module (§8) is configured.
  - `metrics` — rank by telemetry-reported headroom. `priority` is used
    only as a deterministic tie-break when two clusters report equal (or
    missing) telemetry, so the order is never arbitrary.
  - `hybrid` — both signals are in play; which one leads is the second
    setting below.

- **`APP_RECOMMENDATION_PRECEDENCE`** — `priority` \| `telemetry`,
  **default `priority`**. Only consulted when `mode=hybrid`; decides which
  signal is authoritative and which is the secondary check:
  - `precedence=priority` **(default)** — rank by `priority`; telemetry
    acts only as an eligibility **gate**, not a ranking input — a cluster
    over `APP_CAPACITY_THRESHOLD` is skipped and the next-highest-priority
    cluster is tried instead. Telemetry never *reorders*, only *removes
    from contention*. This is the "coexist by not competing" model:
    priority answers *what we prefer*, telemetry answers *is that choice
    usable right now*.
  - `precedence=telemetry` — rank by headroom; `priority` becomes the
    tie-break, same behavior as `mode=metrics`.

Defaulting `APP_RECOMMENDATION_PRECEDENCE` to `priority` means the admin's
static intent wins whenever the two disagree, and telemetry can only ever
**veto** a choice, never **override** it outright.

A **weighted-score blend** (normalize both to 0–1, combine with tunable
weights, rank by the result) was considered and set aside: it lets a
low-priority/high-headroom cluster outrank a high-priority one outright —
a real disagreement between the two signals rather than a gate or a
tie-break — which is harder to explain and audit than either mode above,
and adds two numbers an admin has to tune. Not implemented; revisit only if
`mode`/`precedence` prove too coarse in practice.

Selected via `APP_RECOMMENDATION_MODE` + `APP_RECOMMENDATION_PRECEDENCE`
(§5), using the same name-keyed-registry pattern as the auth (§10) and
telemetry (§8) modules.

### Telemetry failure policy

If `telemetry_module` (§8) is enabled but unreachable at request time,
**`APP_TELEMETRY_FAILURE_POLICY`** (§5) decides what happens to the
ranking, independent of `mode`/`precedence`:

- `fail_open` **(default)** — proceed as if telemetry had reported nothing:
  `hybrid`+`precedence=priority` falls back to pure priority (the gate
  simply excludes no one); `metrics` mode and `hybrid`+`precedence=telemetry`
  fall back to `priority` as the deterministic tie-break for everyone. The
  recommendation still comes back — degraded, not blocked.
- `fail_closed` — refuse to let the affected clusters be recommended when
  the configured mode needs telemetry and can't get it (exact response
  shape — empty `items`, a `503`, or something else — TBD).

Default is `fail_open` because telemetry is designed as a *bonus* signal
(§8), not a hard dependency — an outage in Prometheus (or wherever)
shouldn't stop provisioning fleet-wide when priority alone can still make a
reasonable call. This policy is specific to telemetry/ranking; §9's health
module is a separate, independent mechanism with its own (much simpler)
behavior.

### Tie-break

**Decided:** when two or more clusters end up equally ranked — same
`priority`, and either identical telemetry or telemetry not in play — the
recommendation is chosen **at random** among the tied clusters, re-rolled
on every request (not cached/sticky). Side benefit: this spreads load
across equally-good clusters over many requests, similar to naive
round-robin, without the API needing to track any request history. The
*ordering* of the other tied (non-recommended) members in `items` is
otherwise unspecified — only `items[0]`/`recommended_cluster_id` is
meaningful.

## 8. Telemetry / capacity module (pluggable)

Not required for v1's ranking logic (§3.1 works off registry + priority
alone, `recommendation_mode=priority`, §7 — no telemetry gating). Designed now, wired
in later, exactly as requested — as a swappable module, the same shape as
naas-api's auth registry (`AUTH_MODULES` dict keyed by name, selected via
an env var):

- A `CapacityProvider` interface: given a cluster, return some notion of
  available headroom (used/available/percent — exact shape TBD once a real
  metric is chosen).
- `PrometheusCapacityProvider` — queries a configured Prometheus endpoint
  using a **custom PromQL template**, so the actual query is config, not
  code. Open question: one central Prometheus for the whole fleet, or
  per-cluster/federated instances (changes whether the template needs a
  per-cluster Prometheus URL too) — see §17.
- `NativeAPICapacityProvider` — for clusters whose naas-api (or another
  in-cluster API) already exposes usage/capacity directly, call that
  instead of Prometheus.
- `NoopCapacityProvider` — the `none` default; ranking ignores capacity
  entirely.

Selected via `APP_TELEMETRY_MODULE` (§5), registered the same way naas-api
registers auth modules — a name → factory mapping, so adding a third
provider later is additive.

When enabled, this module feeds into §7's ranking as the telemetry signal —
gating priority (`mode=hybrid`, `precedence=priority`, the default) or
driving the ranking directly (`mode=metrics`, or `mode=hybrid` with
`precedence=telemetry`), depending on the configured mode/precedence. See
§7 for what happens if this module is enabled but its backend can't be
reached (`APP_TELEMETRY_FAILURE_POLICY`).

## 9. Health module (pluggable)

**New, per your request:** `GET /clusters` (§3.1) should never hand back a
cluster whose naas-api instance isn't actually reachable — recommending a
dead cluster means opbox's next call (create a namespace via that cluster's
naas-api) fails, right after naas-discovery told it that cluster was fine.

This is a **separate, independent concern from §8's telemetry module** —
not a variant of it, not sharing its config, not sharing its failure
behavior. Telemetry answers "how much room does this cluster have";
health answers "is this cluster even reachable." The only thing the two
modules share is the general shape of *being pluggable* — an interface
plus swappable implementations, chosen by an env var — the same
lightweight convention this project already uses for auth (§10) and
telemetry (§8):

- A `HealthChecker` interface: given a cluster, report whether it's
  currently healthy.
- `HttpHealthChecker` **(default)** — calls `GET {cluster.endpoint}/healthz`
  (every naas-api instance already exposes this, and it's unauthenticated —
  same as naas-api's own probes, so no credentials are needed to check
  another cluster's health) with a timeout
  (`APP_HEALTH_CHECK_TIMEOUT_SECONDS`); a `2xx` response within the timeout
  means healthy.
- `NoopHealthChecker` — the `none` override; every cluster is treated as
  healthy, i.e. health-check filtering is effectively off (useful for local
  dev against fixture clusters that don't run a real naas-api, or if this
  filtering turns out not to be wanted).

**Background cache, not a live call per request.** Checking every matching
cluster's `/healthz` synchronously on every `GET /clusters` call would add
N network round-trips — and their latency and failure modes — to every
request. So, same pattern as naas-api's own `app/services/cache.py`: a
background task polls every `enabled` cluster's health every
`APP_CLUSTER_HEALTH_CHECK_INTERVAL_SECONDS` and keeps an in-memory
`cluster_id -> healthy` map; `GET /clusters` just reads that cache. Same
"single worker" caveat as naas-api's cache (Dockerfile note, §13): the
poller must not run once per uvicorn worker inside the pod — one process
does it, scale via replicas, not workers.

**How it changes §3.1's result.** Health filtering happens *before* §7's
ranking — the candidate set for a request is
`registry_match(criteria) ∩ enabled ∩ healthy`, and only that filtered set
gets ranked and returned in `items`. An unhealthy cluster doesn't just lose
priority, it's **absent from `items` entirely**.

**No separate failure-policy setting — this module is simply on or off.**
Unlike §7/§8's telemetry, which has a dial for what to do on failure
(`APP_TELEMETRY_FAILURE_POLICY`), health checking has only one behavior
when it's on: a cluster with **no confirmed-healthy status** — whether the
poller hasn't reached it yet, or its last check errored instead of cleanly
reporting up/down — is **always excluded**. There's nothing to configure
because there's only one safe answer: this module exists specifically to
stop an unconfirmed cluster from being recommended, so "unconfirmed" and
"unhealthy" are treated the same, always. If this filtering isn't wanted at
all — local dev against fixtures with no real naas-api, for instance — the
whole module is turned off via `APP_HEALTH_MODULE=none` (§5); there is no
in-between "on, but permissive" mode.

**§3.2 (`GET /clusters/{id}`) is unaffected by this filter** — see §3.2:
a direct lookup by known id still returns the entry regardless of health,
with a `healthy` field reflecting the cache's last-known status.

Selected via `APP_HEALTH_MODULE` (§5), same name-keyed-registry pattern as
auth (§10) and telemetry (§8).

## 10. Authentication — reused from naas-api

Same HTTP Basic module as naas-api, not a re-implementation: `Principal`,
`AuthError`, `BasicAuth` (constant-time password comparison via
`hmac.compare_digest`, `WWW-Authenticate` challenge, OpenAPI `basicAuth`
scheme for the Swagger Authorize button), and the same `AUTH_MODULES`
name → factory registry pattern selected via `APP_AUTH_MODULE`.

Concretely: naas-api's `app/auth/base.py`, `app/auth/basic.py`, and
`app/auth/__init__.py` (~80 lines total, no naas-api-specific dependencies)
get copied into `naas-discovery/app/auth/` — this is a vendor-copy, not a
shared package, deliberately, since the module is small and
dependency-free; a shared internal package is the alternative if the org
later wants one source of truth instead of two copies kept in sync by hand
(open question, §17).

### Users as a file, not just an env var

naas-api's `BasicAuth` module is constructed from a plain `{"user": "pass"}`
dict (`settings.basic_auth_users`) — it doesn't care where that dict came
from. Today that dict is populated from `APP_BASIC_AUTH_USERS`, a JSON
*string* env var. naas-discovery adds a second source for the same dict:
**`APP_BASIC_AUTH_USERS_FILE`**, a path to a **YAML** file holding the same
shape, e.g.:

```yaml
# secrets/basic-auth-users.yaml
admin: changeme
opbox: another-password
```

— more readable/editable by hand than a one-line JSON blob, and consistent
with every other config file in this project (§2's `clusters.yaml`) being
YAML rather than JSON. If set, the file is read at startup and takes
precedence over `APP_BASIC_AUTH_USERS`; if unset, behavior is unchanged
(env var, `{}` default). This only touches `app/core/config.py` (how the
dict is assembled before being handed to `BasicAuth`) — `BasicAuth` itself,
in `app/auth/basic.py`, doesn't change; it still just gets a `dict`.

**Why a file:** it lets the Kubernetes Secret be mounted as a volume
(§12) instead of flattened into container env vars — env vars are visible
via `kubectl describe pod`/`exec env` and end up in more places (crash
dumps, some log aggregators) than a file only the container's own
filesystem can read. This is the same reasoning behind the common
`SOMETHING_FILE` convention (e.g. Docker/Compose secrets).

This is a small deviation from naas-api's current auth module, which only
supports the env var form — worth deciding whether to backport
`_FILE`-suffix support there too so the two vendored copies don't drift
apart (§17).

## 11. Project structure

```
naas-discovery/
  app/
    main.py                composition root
    core/
      config.py             env-driven settings (§5)
      errors.py
    auth/                   vendored from naas-api, unchanged (§10)
      base.py
      basic.py
      __init__.py
    api/
      deps.py
      clusters.py            §3.1 (list + recommend) / §3.2 (get) — one router, no separate resolve route
    models/
      clusters.py             request/response schemas
    registry/                 §4
      base.py                  RegistrySource interface
      file_source.py           YAML-file-backed implementation
    recommend/                  §7
      strategies.py              priority / telemetry / hybrid ranking
    telemetry/                 §8
      base.py                   CapacityProvider interface
      noop.py
      prometheus.py
      native_api.py
    health/                     §9
      base.py                   HealthChecker interface
      noop.py
      http.py                   HttpHealthChecker
      cache.py                  background poller + in-memory status map
  config/
    clusters.yaml               now also carries each cluster's `priority` (§7)
  helm/
    naas-discovery/            §12
  docs/
    design/
      naas-discovery-design.md   this document
  Dockerfile                   §13
  docker-compose.yml            §13
  requirements.txt
```

## 12. Kubernetes deployment (Helm)

Mirrors naas-api's chart (`Chart.yaml`, `values.yaml`,
`templates/{deployment,service,configmap,secret,ingress,route,
serviceaccount,_helpers.tpl,NOTES.txt}.yaml`), with these differences:

- **Single central Deployment**, not one per cluster. `replicaCount` can be
  >1 more freely than naas-api — there's no in-cluster mutation to
  serialize. §9's health-check poller (and any future in-process cache)
  does run per-pod, same "single worker inside the pod" caveat as naas-api's
  own cache (§13's Dockerfile note) — but each replica polling and caching
  independently is fine, since it's read-only against other clusters and
  needs no cross-replica coordination.
- **No RBAC / cluster-facing ServiceAccount permissions** by default — this
  service doesn't talk to the Kubernetes API of the cluster it runs on,
  unlike naas-api. That could change if the Prometheus module (§8) needs an
  in-cluster service-account token to reach a co-located Prometheus —
  depends on the "one Prometheus vs. per-cluster" open question in §17.
- **Egress** — §9's health module (on by default) needs outbound network
  reachability from naas-discovery to every enabled cluster's naas-api
  endpoint (`/healthz`). If the namespace's default NetworkPolicy blocks
  egress, this chart needs to ship one allowing it — worth confirming
  alongside the RBAC question above (§17).
- **ConfigMap** mounts `clusters.yaml` as a file (not flattened into env
  vars, since it's structured YAML) at the path from §5.
- **Secret** — unlike naas-api's `secretRef` (flattened into env vars), the
  Basic Auth users Secret here is mounted as a **volume**, at the path
  `APP_BASIC_AUTH_USERS_FILE` points to (e.g.
  `/etc/naas-discovery/secrets/basic-auth-users.yaml`) — see §10 for why.
  `values.yaml` still takes `auth.basicUsers` as a map at install time
  (`--set-json 'auth.basicUsers={"admin":"..."}'`, same UX as naas-api);
  the chart renders it into the Secret's file content instead of into env
  vars.
- **Ingress/Route** — same either/or pattern as naas-api (enable at most
  one).

## 13. Docker & local development

- **Dockerfile** — same base pattern as naas-api: `python:3.12-slim`,
  arbitrary-UID-friendly permissions (`chgrp -R 0` / `chmod g=u`) for
  OpenShift, non-root `USER`, single worker
  (`uvicorn app.main:app`, no `--workers`) — §9's health-check poller must
  not run multiple times inside one pod, same reasoning as naas-api's own
  cache-thread constraint; scale via replicas, not workers.
- **docker-compose.yml** — an `app` service for local runs against a
  bind-mounted `config/clusters.yaml` and a bind-mounted local users file
  (e.g. `secrets/basic-auth-users.yaml`, gitignored, with
  `APP_BASIC_AUTH_USERS_FILE` pointed at its mount path) so local dev
  matches the file-based Secret used in Helm, plus a `tests` service
  mirroring naas-api's bind-mounted pytest runner
  (`docker compose run --rm tests`). If the Prometheus module is being
  exercised locally, a local Prometheus (or a lightweight mock exposing the
  same query API) can be added as a third compose service — deferred until
  §8 is actually built. For local runs against fixture clusters that don't
  run a real naas-api, set `APP_HEALTH_MODULE=none` so §9's default health
  filtering doesn't just exclude everything.

## 14. Observability

Structured stdout events, same style as naas-api's, emitted by the single
`GET /clusters` handler whenever the request carries filters (an unfiltered
full-registry dump isn't a "decision" worth auditing the same way):
`event=clusters_query region=... environment=... labels=...` followed by
`event=clusters_query_result recommended=... candidates=... basis=priority|metrics`
(or `event=clusters_query_no_match ...`). `candidates` reflects the
post-health-filter set (§9). Since the recommendation determines *where a
workload physically lands*, this is the audit trail for that decision —
treat it with the same seriousness as naas-api's create/delete events.

§9's background poller separately logs each cycle:
`event=health_check_result cluster_id=... healthy=true|false latency_ms=...`
(`healthy=false` covers both a confirmed-down `/healthz` and a check that
errored/timed out — both are excluded the same way, see §9).

## 15. Security & operational notes

- Reused Basic Auth (§10) — no new auth surface to review.
- Registry config should be validated at startup (malformed YAML, duplicate
  `cluster_id`, an out-of-range `priority`) — fail fast rather than serving
  a partially-broken registry.
- A recommendation from a filtered `GET /clusters` call drives real
  provisioning decisions downstream (via naas-api on the returned endpoint)
  — log every such request/response (§14) as the audit trail, including
  which basis (priority/metrics) produced the recommendation.
- `APP_TELEMETRY_FAILURE_POLICY` (§5/§7) controls what happens when the
  telemetry backend is unreachable, default `fail_open` — see §7 for the
  full rationale. This is specific to §7/§8's ranking; §9's health module
  is unrelated and has no equivalent setting (see next point).
- §9's health module has **no failure-policy setting** — it's a binary
  on/off (`APP_HEALTH_MODULE`), and while on, an unconfirmed-healthy
  cluster is always excluded, never configurable to "include anyway." See
  §9 for why that's the one safe answer here.
- §9's health checks are plain, unauthenticated outbound HTTP requests to
  other clusters' `/healthz` — nothing sensitive is sent or exposed by the
  check itself, but see §12's Egress/NetworkPolicy note for what it
  requires from the network.

## 16. Testing strategy

Mirrors naas-api's fake-based approach:
- **Unit** — registry matching (§6) against a fixture `clusters.yaml`;
  recommendation ranking (§7) for each `mode`/`precedence` combination,
  including `APP_TELEMETRY_FAILURE_POLICY` behavior and the random
  tie-break (statistical — assert every tied candidate shows up as the
  recommendation across many repeated calls, not just one); each telemetry
  provider (§8) against a fake Prometheus/native-API client; each health
  checker (§9) against a fake HTTP client (healthy, unhealthy, and
  timeout/error), verifying that both unhealthy *and* unknown-status
  clusters are excluded from `GET /clusters` — no third "included anyway"
  path to test, since there isn't one; the auth module (already covered by
  naas-api's own tests — just confirm the vendored copy still passes the
  same suite).
- **Functional** — `TestClient` against `/clusters` (unfiltered, filtered
  to one match, filtered to multiple matches — the multi-dev-cluster case
  with the recommended entry landing first, filtered to zero matches, and a
  match set where some clusters are unhealthy and get excluded) and
  `/clusters/{id}` (returns even when unhealthy, with the `healthy` field
  set correctly); auth 401s; OpenAPI security advertisement.

## 17. Open questions

1. **Exact meaning of the `enabled` boolean** (§2) — is it the full extent
   of the "yes/no" field you mentioned, or is there a second boolean
   (e.g. "accepts new namespaces" separate from "cluster exists/is up")?
2. **`APP_CAPACITY_THRESHOLD` default** — the reconciliation mechanism
   itself is decided (§7: `mode`/`precedence`, priority wins by default);
   what's still open is the actual headroom cutoff the priority-precedence
   gate should use once §8 exists.
3. **Telemetry/PromQL schema** — one fleet-wide Prometheus vs.
   per-cluster/federated instances; exact query template shape. Explicitly
   deferred by you to a later discussion.
4. **`GET /clusters` verb** — stay with `GET` + query params, or move to
   `POST` + JSON body once filters (or the recommendation inputs) get more
   complex/nested (e.g. multiple label requirements)?
5. **Auth module packaging** — keep as a vendored copy in each repo
   (recommended for now, §10) or extract to a shared internal package once
   there's a second consumer to justify the overhead? Also: should the new
   `APP_BASIC_AUTH_USERS_FILE` support (§10) be backported into naas-api's
   copy of the module too, so both stay in sync?
6. **RBAC/ServiceAccount and Egress need** — depends on where Prometheus
   ends up living relative to this service (§12); separately, whether
   §9's health-check egress to every cluster's naas-api needs an explicit
   NetworkPolicy or is already allowed by the namespace's default posture.
7. **"opbox" identity** — is it a specific existing tool, a human via CLI,
   or the same orchestrator that also calls naas-api directly? Doesn't
   change this design, but could add requirements (e.g. a caching/TTL hint
   in the `GET /clusters` response, or an idempotency key) worth knowing
   about early.
8. **`provider` taxonomy** (§2) — confirmed to be an internal designation,
   not a cloud vendor, but the actual set of valid values and what they
   represent organizationally isn't defined yet.
9. **`/healthz` being unauthenticated on every cluster's naas-api** (§9) —
   assumed true based on naas-api's own README (probes are listed outside
   `/api/v1`'s auth requirement), but worth confirming that holds for every
   real deployment (no ingress-level auth in front of it) — otherwise the
   health module would need per-cluster credentials too, which it
   currently doesn't have a way to carry.
10. **`APP_HEALTH_MODULE` default of `http` (on)** (§9) — this is the one
    module in the design that defaults *on* rather than `none`, since you
    asked for it as protective default behavior; flagging the asymmetry
    with telemetry's default-off posture in case that's not intended.

## 18. Phased plan

1. **Registry + ranked list, priority-only, with health filtering.**
   `clusters.yaml`-backed registry (with `priority` per cluster), a single
   `GET /clusters` (list + recommendation together) and
   `GET /clusters/{id}`, ranked by `priority` alone
   (`recommendation_mode=priority`, §7) with no telemetry gating yet — but
   **§9's health module (`HttpHealthChecker`, on by default) included from
   the start**, since it's foundational correctness rather than an
   enhancement — vendored Basic Auth (+ file-based users, §10), Dockerfile
   + Helm chart + Compose.
2. **Telemetry module + hybrid gating.** `CapacityProvider` interface +
   `Prometheus` implementation, wired into §7's `hybrid`/`priority`-
   precedence gate once `APP_CAPACITY_THRESHOLD` (§17.2) is set;
   `APP_TELEMETRY_FAILURE_POLICY` exercised here too.
3. **Extensibility + hardening.** First-class support for additional
   filters beyond region/environment (team, etc.) via the generic `labels`
   model (§6); `native_api` telemetry provider; startup config validation.
