# News Codex

Audited source intelligence registry for AI and developer news. Phase one validates, probes,
versions, and reports on sources before downstream summarization is enabled.

## Requirements

- Python 3.12+
- `uv`
- PostgreSQL 14+
- No Docker is required or used

## Local setup

```powershell
uv sync --extra dev
Copy-Item .env.example .env
# If PostgreSQL is outside C:\Program Files\PostgreSQL, set POSTGRES_HOME in .env.
uv run newsradar db init
uv run alembic upgrade head
uv run newsradar providers sync --root providers
uv run newsradar sources sync --root sources
```

Never put an API key in `sources/*.yaml`. Credentials are read from environment variables only.

## Project-local PostgreSQL

News Codex uses an isolated PostgreSQL cluster at `127.0.0.1:55432`. It does not start,
stop, or reconfigure an existing Windows PostgreSQL service. The generated database password
is stored only in the Git-ignored `.env`; database files and logs are stored below the
Git-ignored `.local/postgres/` directory.

```powershell
# Direct CLI
uv run newsradar db init
uv run newsradar db start
uv run newsradar db status
uv run newsradar db stop

# Equivalent PowerShell wrapper
.\scripts\postgres.ps1 -Action status
```

`init` is idempotent and preserves other `.env` settings. Set `POSTGRES_HOME` to the directory
containing PostgreSQL's `bin` folder when PostgreSQL is installed in a nonstandard location,
for example `D:\software\postsql`. Port `55432` is fixed; initialization fails instead of
silently selecting another port when it is occupied.

Deleting `.local/postgres/` permanently deletes the project database. Stop it first and back up
anything important. The lifecycle commands never delete this directory automatically.

## Chinese source dashboard

Start the local database, apply migrations, sync the audited catalogs, and launch the dashboard:

```powershell
uv run newsradar db start
uv run alembic upgrade head
uv run newsradar providers sync --root providers
uv run newsradar sources sync --root sources
uv run newsradar web
```

Open `http://127.0.0.1:8765`. The dashboard is a local, read-only view of PostgreSQL: browsing it
does not sync definitions, run probes, change source status, or write probe history. Launching and
browsing the dashboard does not call MiniMax or any other model API.

The dashboard uses these terms deliberately:

- **Registered** means an audited provider or target is present in the catalog. Registration does
  not claim that News Codex can read its content.
- **Directly readable** means an approved access method reads the target itself when its access
  requirements are met.
- **Indirectly discoverable** means an aggregator or search path can surface a reference to the
  target; it does not claim direct access to the target's content.
- **Capability-probed** means a provider-level check tested whether an access capability was
  available. It does not mean target content was fetched.
- **Content-probed** means a target-level check inspected content availability and structure at a
  recorded point in time. It does not imply continuous ingestion or current coverage.

## Source workflow

```powershell
uv run newsradar sources validate --root sources
uv run newsradar sources sync --root sources
uv run newsradar sources probe --all --root sources
uv run newsradar sources probe hackernews-top --root sources --no-persist
uv run newsradar sources report --root sources --output reports/source-intelligence.md
```

When database credentials are not configured, use `--no-persist`. A live report can still be
created from the network run:

```powershell
uv run newsradar sources probe --all --root sources --no-persist `
  --report-output reports/live-source-intelligence.md
```

YAML is the audited source of truth. Probe history and immutable YAML versions belong in
PostgreSQL. Probe results never rewrite YAML or automatically activate a source.

## Source Universe v2

Providers describe platform-level access, policy, authentication, cost, and capabilities.
Sources describe concrete publisher feeds, accounts, channels, communities, queries, and signals.
Catalog coverage never implies that content is being ingested.

```powershell
uv run newsradar providers validate --root providers
uv run newsradar providers sync --root providers
uv run newsradar providers probe --all --root providers
uv run newsradar sources coverage --provider-root providers --root sources `
  --history --output reports/source-coverage.md
uv run newsradar sources coverage --provider x --provider-root providers --root sources
```

Restricted platforms remain visible as `requires_credentials`, `requires_approval`,
`requires_payment`, or `manual_only`. News Codex never falls back to account cookies, browser
sessions, CAPTCHA bypass, or unaudited scraping. Social content is a discovery/engagement signal;
it is not treated as verified evidence by itself.

## MiniMax

The constrained adapter supports:

- `MiniMax-M2.7-highspeed` for source classification and topic inference
- `MiniMax-M3` for explaining probe failures and future event-level synthesis

MiniMax is optional in phase one. Without `MINIMAX_API_KEY`, deterministic rules remain usable.
All source content is marked as untrusted, tool use is disabled, responses are validated with
Pydantic, and invalid JSON gets at most one repair attempt.

## Quality gates

```powershell
uv run ruff check .
uv run pytest
```

The current catalog spans professional media, first-party sources, social/community platforms,
aggregators/search, research/developer sources, newsletters/podcasts, and trend/business signals.
X and other restricted platforms are cataloged with explicit unlock requirements rather than
being silently omitted or scraped through high-risk methods.
