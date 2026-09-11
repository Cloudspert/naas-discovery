# Dev log

A running log of implementation decisions, deviations from the design doc,
and things flagged for human confirmation — kept separate from the design
doc itself (`docs/design/naas-discovery-design.md`), which describes
*intent*, not *what actually got built and why*.

**If you are an LLM session resuming work on this repo: read this file
before making changes, and add a new dated entry (below, newest first)
for anything non-obvious you decide, change, or discover — especially if
you deviate from the design doc, resolve one of its open questions, or
make a judgment call it left unspecified.** Don't rewrite history here;
append. If a past entry turns out to be wrong, add a new entry that says
so and why, rather than editing the old one away. See `CLAUDE.md` for the
pointer that brought you here.

---

## 2026-09-11 — Initial build

Built the full application per the design doc (all sections, not just
Phase 1 — see design doc §18; the user explicitly chose to build
everything already-specified, including the Prometheus telemetry
provider, rather than stopping at Phase 1). Dependency versions were
pinned to latest-stable-as-of-today rather than mirrored from naas-api's
exact pins (also an explicit choice, not a default) — see `requirements.txt`
if naas-api's own pins move and these should be reconciled later.

All 61 tests pass (`pytest`, `docker compose run --rm tests`). The
Dockerfile, docker-compose.yml, and Helm chart were all actually
exercised, not just written: `docker compose build`, `docker compose up
app` against a live container, `helm lint` + `helm template` with
representative `--set`/`--set-json` values, and — importantly — the
Helm-rendered `clusters.yaml` and `telemetry.yaml` were piped through the
real `FileRegistrySource`/`TelemetryConfig` Python models to confirm they
actually parse, not just that the YAML is well-formed.

### Decisions made where the design doc was silent or ambiguous

1. **`capacity_threshold` direction — was a bug in the design doc,
   confirmed and fixed 2026-09-11.** §7 of the design doc said a cluster
   "over `CLUSTER_CAPACITY_THRESHOLD` is skipped." But `CapacityProvider`
   is specified (§8) as returning *available headroom* — higher is better.
   Read literally, "skip when over threshold" would exclude the clusters
   with the *most* room, which contradicted "headroom." Implemented as:
   exclude when `headroom < threshold` (not enough room) — see
   `app/recommend/strategies.py`'s module docstring. **User confirmed this
   reading is correct**; the design doc's §7 wording was updated to match
   ("below" instead of "over"). No further action needed here.

2. **`enabled` is not a caller-facing query filter.** Design doc §3.1
   lists `enabled` as one of the optional query params, but also says the
   endpoint "always returns every enabled cluster that matches" without
   qualification — those two statements conflict (this is design doc open
   question §17.1). Implemented the conservative reading: disabled
   clusters are never returned, full stop, and `enabled` is not accepted
   as a query parameter at all (`app/registry/matching.py`). If the intent
   was actually "let callers ask for disabled clusters too," that's a
   different, larger change (the whole response shape would need an
   `enabled` field per item, which it already has, so it's not a big
   lift — just not what's built today).

3. **`fail_closed` for telemetry means "excluded from the candidate set,"
   not a distinct error response.** Design doc §7 explicitly marks the
   exact behavior "TBD" ("empty `items`, a `503`, or something else").
   Implemented as: a cluster whose headroom couldn't be determined is
   simply dropped from ranking (same as a filtered-out cluster) — the
   request still returns `200`, possibly with fewer `items` than
   `fail_open` would have returned, never `items: []`-as-error or a `5xx`.
   Reasoning: this matches how the *health* module's exclusions already
   work (never an error status), so the API doesn't need two different
   "why isn't my cluster here" response shapes depending on which module
   excluded it.

4. **Prometheus query HTTP timeout is hardcoded** at 5 seconds
   (`app/telemetry/prometheus.py::QUERY_TIMEOUT_SECONDS`), not a setting.
   The design doc doesn't define a telemetry-specific timeout. If this
   needs to be tunable, add `CLUSTER_TELEMETRY_QUERY_TIMEOUT_SECONDS` to
   `app/core/config.py` and thread it through — small change, not done
   because nothing in the conversation asked for it.

5. **Hybrid + `precedence=priority` with no `capacity_threshold` set**
   degrades to plain priority ranking (telemetry is fetched but nothing
   gates on it, since there's no threshold to gate against). Not specified
   either way in the design doc; seemed like the only sane behavior short
   of refusing to serve the request.

6. **Auth realm string changed from `"naas-api"` to `"naas-discovery"`**
   in the vendored `app/auth/base.py` — the design doc says the auth
   module is "vendored... unchanged," but copying the realm string
   verbatim would have been actively wrong (it's user-visible, in the
   `WWW-Authenticate` header). This is the one deviation from "unchanged."

7. **Helm's `telemetry.yaml` Secret template hand-renders each override
   field** (`helm/naas-discovery/templates/secret.yaml`) instead of a
   blind `toYaml` on `.Values.telemetry.overrides`, because `values.yaml`
   uses Helm's camelCase convention (`prometheusUrl`) while
   `app/telemetry/config.py`'s `TelemetryOverride` model expects
   snake_case (`prometheus_url`) — a blind `toYaml` would have silently
   produced a file the Python side couldn't read (pydantic ignores unknown
   fields by default, so no error, just a config that quietly does
   nothing). **If you add a field to `TelemetryOverride`, you must also
   add it to this template by hand** — there's no automatic sync between
   the two. Caught by actually parsing the Helm-rendered output through
   the real pydantic model during this build, not by inspection.

8. **`app/telemetry/native_api.py` is a stub** (raises `NotImplementedError`
   in `__init__`) — Phase 3 in the design doc, genuinely not designed in
   enough detail to build (what endpoint, what response shape).

### Still open (unchanged from design doc §17, not re-litigated here)

Actual PromQL query content, `provider` taxonomy, "opbox" identity,
whether bearer-token Prometheus auth is needed (current implementation is
Basic Auth / unauthenticated only, per the user's explicit schema),
RBAC/egress confirmation for the health module, backporting
`CLUSTER_BASIC_AUTH_USERS_FILE` support into naas-api's own auth module.
