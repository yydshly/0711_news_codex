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

The current catalog contains first-party RSS feeds, GitHub releases, Hacker News, arXiv,
conditional Reddit sources, and discovery-only aggregators. X and high-risk Chinese social
scraping are intentionally outside phase one.
