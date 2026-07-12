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
uv run newsradar db repair

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
uv run newsradar serve
```

Open `http://127.0.0.1:8765`. `serve` starts the Web UI and the durable Worker together and is the
recommended daily runtime. Browsing pages does not fetch external content. Fetch enqueue, cancel,
retry, duplicate review, and diagnostic bundle actions write audited local state; only the Worker
performs source network requests. Launching and browsing the dashboard does not call MiniMax.

Use the individual modes for diagnosis:

```powershell
uv run newsradar web
uv run newsradar worker --once
uv run newsradar worker --forever
uv run newsradar fetch hackernews-top --root sources --no-wait
```

If only `web` is running, fetch requests remain queued until a Worker starts. `db repair` repairs
only deterministic partial local states; it never deletes `.local/postgres` or its logs.

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

## Public social and discovery ingestion

Only source targets with `ingestion.enabled: true` and a recorded `approved_at` date may be run
through ingestion. Use the explicit dry-run path for an operational check; it performs the bounded
network fetch but does not persist raw items or cursor state:

```powershell
uv run newsradar fetch bluesky-bsky --root sources --dry-run --max-items 1
uv run newsradar fetch mastodon-mastodon --root sources --dry-run --max-items 1
uv run newsradar fetch google-news-ai --root sources --dry-run --max-items 1
uv run newsradar fetch gdelt-ai --root sources --dry-run --max-items 1 --one-off
```

Public social accounts provide discovery, engagement, and context only. Google News, GDELT, and
other aggregators preserve their discovery URL and require original-publisher attribution before an
item can support evidence. Do not treat snippets, reposts, engagement counts, or an unresolved
aggregator link as independent verification. Operators must not use cookies, logins, browser
sessions, or HTML/article scraping to work around a failed public endpoint.

Operational logs bind a correlation ID to each operation and redact credentials and response
payloads. Record endpoint status, item counts, and error codes—not feed bodies or API responses—in
run reports.

GDELT 默认不进入常规抓取。它当前标记为 `degraded`，只保留发现能力、人工探测和明确确认后的
`--one-off` 路径，不能作为唯一事实来源。

## Credentials and risk

Credentials live only in the Git-ignored `.env`. The UI shows variable names and whether each is
configured, never the values.

- `GITHUB_TOKEN`: optional read-only token for higher GitHub API limits; grant no write scopes.
- `REDDIT_CLIENT_ID` and `REDDIT_CLIENT_SECRET`: an official OAuth application pair; revocation,
  policy, rate-limit, and account-approval risks remain.
- `YOUTUBE_API_KEY`: a Google Cloud project key subject to quota and billing-project policy; restrict
  it to the YouTube Data API and local use where possible.

Never copy keys into YAML, reports, diagnostics, logs, screenshots, commits, or issue text.

## MiniMax

The constrained adapter supports:

- `MiniMax-M2.7-highspeed` for source classification and topic inference
- `MiniMax-M3` for explaining probe failures and future event-level synthesis

MiniMax is optional in phase one. Without `MINIMAX_API_KEY`, deterministic rules remain usable.
All source content is marked as untrusted, tool use is disabled, responses are validated with
Pydantic, and invalid JSON gets at most one repair attempt.

MiniMax 适配器尚未接入 RawItem v1.1。当前抓取、来源健康、资格判断、任务控制和重复候选裁决
不依赖模型，也不会自动生成新闻摘要或推荐。

## Event intelligence v1

Event builds are durable operations: the web route or CLI only queues work, and a Worker publishes
completed immutable event versions. The homepage keeps its 24-hour confirmed-event window; use a
wider build window only for a separately labelled operational coverage check.

```powershell
uv run newsradar serve
uv run newsradar fetch --no-wait
uv run newsradar events build --hours 24
uv run newsradar operations list
```

Open `/`, `/events`, `/emerging`, and `/events/<id>` on the local UI. Event details retain original
evidence links, roles, and independent-root information. MiniMax is optional: when it is not
configured, rule-based enrichment continues without a model request. Never put credentials, feed
bodies, or unredacted upstream error URLs in acceptance notes; see
`reports/event-intelligence-v1-acceptance.md` for scrubbed operational evidence.

Use `operations list` to observe the fetch terminal status while the Worker is running. The current
`fetch --wait` output path has a known post-completion status-rendering defect and is not the
recommended operator workflow.

## Quality gates

```powershell
uv run ruff check .
uv run pytest
```

The current catalog spans professional media, first-party sources, social/community platforms,
aggregators/search, research/developer sources, newsletters/podcasts, and trend/business signals.
X and other restricted platforms are cataloged with explicit unlock requirements rather than
being silently omitted or scraped through high-risk methods.
