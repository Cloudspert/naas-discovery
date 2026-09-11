# naas-discovery

A centrally-deployed cluster discovery/recommendation API, sibling project
to `naas-api` (which deploys once per cluster). Full context lives in three
places, **read them in this order** before making non-trivial changes:

1. [docs/design/naas-discovery-design.md](docs/design/naas-discovery-design.md)
   — the design doc. *Why* the system is shaped this way. 18 sections, an
   "Open questions" section (§17) that is genuinely still open, and a
   phased plan (§18).
2. [docs/DEV_LOG.md](docs/DEV_LOG.md) — a dated, append-only log of
   implementation decisions, deviations from the design doc, and bugs
   caught while building. **Read this before touching `app/recommend/`,
   `app/registry/matching.py`, `app/telemetry/`, or `helm/`** — several
   non-obvious calls were made in those areas and are recorded there, not
   in code comments alone.
3. [docs/DEVELOPER.md](docs/DEVELOPER.md) — a module-by-module code
   walkthrough and the request flow. The *how*.

## The standing instruction for this project

**Do not assume — ask.** This came directly from the user, repeatedly,
throughout the conversation that produced this codebase, and it still
applies. Concretely:
- If the design doc and DEV_LOG don't settle a question your change
  depends on, ask the user rather than picking silently. If you're in a
  context where you genuinely cannot ask (e.g. an autonomous run), make
  the smallest defensible choice, then **write a new dated DEV_LOG.md
  entry** explaining exactly what you assumed and why, in enough detail
  that a human can spot and correct it later.
- **Every session that changes logic — not just adds tests or fixes a
  typo — must add a new entry to `docs/DEV_LOG.md`** (newest first, don't
  edit old entries away, add a correcting entry instead if one turns out
  wrong). This is how the *why* behind this codebase survives across
  sessions instead of living only in a chat transcript nobody re-reads.
- If you resolve one of the design doc's §17 open questions during a
  session (the user gives you an answer), update the design doc itself,
  not just the code — this repo's convention (see the design doc's own
  git history) is that the design doc is real documentation, kept current.

## Known sharp edges (see DEV_LOG.md for full detail)

- `app/recommend/strategies.py`'s `capacity_threshold` comparison
  direction (`headroom < threshold` excludes) is this build's
  *interpretation* of the design doc, not a confirmed decision — flagged,
  not resolved.
- `helm/naas-discovery/templates/secret.yaml` hand-renders each
  `telemetry.overrides` field because Helm's camelCase values don't
  automatically match `app/telemetry/config.py`'s snake_case model fields.
  Adding a field to `TelemetryOverride` without updating that template
  will silently produce a config the app can't read.
- `get_settings()` (`app/core/config.py`) is `@lru_cache`d — tests must
  clear it between runs (see `tests/conftest.py`); don't remove that
  fixture without understanding why it's there.

## Commands

```bash
python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements-dev.txt
pytest                                    # full test suite
docker compose run --rm tests             # same, containerized
docker compose up app                     # run the API locally at :8080
helm lint helm/naas-discovery             # chart sanity check
helm template test helm/naas-discovery    # render the chart
```
