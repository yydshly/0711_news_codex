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

## 失败来源修复流程

来源修复台用于处理某个固定 UTC 基线下“原本符合公开试用前置条件、但内容探测失败”的
Target。它不会扫描全部非成功记录，也不会把仅目录、间接发现、需要凭据或条款硬阻塞的来源
误算为待修复来源。当前 2026-07-13 基线固定为 27 项；修复前可试用来源为 16，受控验证后为
37。完整证据见 `reports/source-failure-remediation.md`，原始与修复后基线说明见
`reports/source-trial-baseline.md`。

先生成不可变清单，再同步人工审核的 YAML，最后逐个排队候选探测：

```powershell
uv run newsradar sources remediate snapshot `
  --baseline-at 2026-07-13T11:47:00Z `
  --output reports/source-failure-remediation.md
uv run newsradar sources sync --root sources
uv run newsradar worker --root sources --forever --worker-id source-remediation-runtime
uv run newsradar sources remediate queue anthropic-sdk-releases github-releases-api `
  --original-probe-id 38 --baseline-at 2026-07-13T11:47:00Z --wait
uv run newsradar sources remediate report `
  --baseline-at 2026-07-13T11:47:00Z --root sources `
  --output reports/source-failure-remediation.md
```

`queue` 每次只接受一个 Target 和一个已同步候选；网络请求只由 Worker 执行。Worker 的
`--root` 必须指向与 `sources sync` 相同的审核目录，否则会明确返回候选不存在。只有分类为
`network_transient` 的修复操作允许人工执行一次 `sources remediate retry <operation-id>`；
401/403、429、字段不完整、条款阻塞和未知错误不会自动重试。

默认 `HTTP_TRUST_ENV=true`，HTTP 客户端继承当前进程可见的系统网络环境；项目不保存或展示
具体代理配置，也不使用代理轮换绕过平台限制。HTML 仍只允许人工审核的静态研究候选，不执行
JavaScript、不携带 Cookie 或登录态、不生成 RawItem。X、Facebook、Instagram、LinkedIn、
TikTok 等受限平台在没有官方凭据、审批或付费条件时保持明确阻塞，不回退到登录网页抓取。

启动本地服务后访问 `/remediation` 查看候选方式和最新研究探测；`/probes` 查看内容探测，
`/operations` 与 `/fetch-runs` 查看 Worker 操作和试用抓取结果。浏览这些页面本身不会发起
网络抓取。

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

The constrained adapter uses MiniMax's current OpenAI-compatible `/v1/chat/completions` API and
supports:

- `MiniMax-M2.7-highspeed` for source classification, topic inference, and bounded event enrichment
- `MiniMax-M2.7` for probe-failure and disputed-event explanations

Set `MINIMAX_BASE_URL=https://api.minimax.io` for international keys. China-region Token Plan keys
must use `MINIMAX_BASE_URL=https://api.minimaxi.com`; using the wrong region returns HTTP 401 even
when the key and subscription are valid.

MiniMax is optional in phase one. Without `MINIMAX_API_KEY`, deterministic rules remain usable.
All source content is marked as untrusted, reasoning is separated from final content, responses are
validated with Pydantic, and JSON or schema errors get at most one repair attempt.

Use `uv run newsradar minimax check` to inspect the local configuration without a network request;
`uv run newsradar minimax check --live` makes one bounded model-visibility and structured-response
check. Both commands only print configuration state, region, models, outcome, token counts, and
latency—never the key, endpoint, prompt, or provider response body.

MiniMax 适配器尚未接入 RawItem v1.1。当前抓取、来源健康、资格判断、任务控制和重复候选裁决
不依赖模型，也不会自动生成新闻摘要或推荐。

## 来源研究 v3

来源研究页把“平台能否访问”和“某个具体来源能否获得所需信息”分开说明：

- **Provider** 是平台级档案，记录认证、审批、费用、条款和平台能力，例如 YouTube、X、
  Mastodon。
- **Target** 是具体媒体栏目、账号、频道、社区或查询目标，例如 OpenAI YouTube 频道。
- **Wanted Information** 是希望从 Target 获得的字段，不代表这些字段已经可以稳定取得。
- **候选方式** 是针对一个 Target 分别研究的 Atom、API、Sitemap、HTML 或第三方库路径；
  首选、补充、备用和仅人工方式不会相互冒充。

先执行只读目录审计，再按单个候选执行有界探测：

```powershell
uv run newsradar sources research validate --root sources --provider-root providers
uv run newsradar sources research audit --root sources --provider-root providers
uv run newsradar sources research report --root sources --provider-root providers `
  --output reports/source-research-v3-matrix.md
uv run newsradar sources research probe openai-youtube `
  --candidate youtube-atom --limit 5 --no-persist
```

本地数据库可用并已同步候选时，可移除 `--no-persist` 保存脱敏探测记录。上述命令只研究
候选方式，不修改 YAML、不自动启用生产抓取，也不调用 MiniMax。启动本地服务后访问
`/research` 查看中文总览，进入 `/research/targets/<source-id>` 查看所需信息、候选方式、
样本、限制、证据和人工结论。

YouTube 的四条路径用途不同：

- **YouTube Atom**：官方、无需认证，负责发现频道公开视频和基础元数据。
- **YouTube Data API**：官方 API，使用 `YOUTUBE_API_KEY` 补充描述和互动量；无 Key 时明确
  返回凭据阻塞，不回退到网页或登录态。
- **youtube-transcript-api**：非官方第三方库，只对人工选定的公开视频读取有界文字样本；
  字幕关闭、区域限制或库失效都必须可降级。
- **yt-dlp**：当前仅作为人工元数据研究对象，程序不执行视频或音频下载。

HTML 研究只允许对已经人工确认的 HTTPS 页面执行静态、有限大小的请求，解析 canonical、
JSON-LD、Open Graph 和语义标签。它不执行 JavaScript，不使用浏览器会话、Cookie、代理、
验证码绕过，也不会因为一次研究样本就自动成为生产抓取方式。robots 允许访问不等于条款
允许再利用，最终启用仍需逐来源人工结论。

凭据只保存在 Git 忽略的 `.env`。使用最小权限：YouTube Key 只开放 YouTube Data API 并
限制调用来源；GitHub Token 只读；Reddit OAuth 使用独立本地应用并可随时撤销。需要 OAuth、
平台审批或付费的 Provider，网页只显示环境变量名、解锁步骤和风险，不显示值。X、LinkedIn、
TikTok 等受限平台仍登记在来源地图中，但在获得官方授权前不声称具有直接内容覆盖。

## 事件情报 v2.1

事件构建是持久化 Operation：网页或 CLI 只负责入队，Worker 执行规则、有限的 MiniMax
辅助、重试与发布不可变事件版本。首页只展示 `hotspot`；证据尚不足、预印本或低置信度内容
进入 `signal`，噪声和被拒绝事件保留在 `audit_only`，三者不会混排。

高价值波次当前固定 41 个目标。聚合、社区和社交入口用于发现；官方一手来源或两个独立
专业媒体证据根才能把事件升级为“已确认”。运行详情页显示证据型成员、直接证据抓取成功数、
确认事件数和 MiniMax 保守回退数。MiniMax 关闭时规则管线仍会完成。

```powershell
uv run newsradar serve --host 127.0.0.1 --port 8766 --worker-id newsradar-local
uv run newsradar fetch --no-wait
uv run newsradar events build --hours 24
uv run newsradar events quality-report --window-hours 72 --output reports/event-quality-v2-1.md
uv run newsradar operations list
```

`serve` 是本机推荐的唯一日常运行入口，会同时启动 Web 与 Worker。系统页会显示 Worker
在线空闲/忙碌状态、MiniMax 脱敏配置与最近调用结果。来源恢复探测先运行
`uv run newsradar sources health-wave` 查看计划，确认后再增加 `--execute`；默认并发上限为 8。

本地网页通过 `/`、`/events?tier=hotspot`、`/events?tier=signal` 和 `/events/<id>` 查看。
详情页保留证据链接、角色、独立证据根、分层与排名依据。MiniMax 是可选辅助：未配置或不可用
时规则管线仍会完成；低价值线索不会自动调用模型。质量报告只读数据库，不触发抓取、事件构建
或模型调用，并汇总新闻价值覆盖、事件分层、成员/证据根、候选对、token 和剩余问题。

`fetch --wait` and `events build --wait` retain terminal scalar state before their SQLAlchemy
session closes, avoiding detached-instance failures while rendering terminal status.

## 自动日报

自动日报在精确事件快照生成后，会对最终进入决策简报或情报全览的唯一事件执行有界中文增强。同一事件在一份日报中最多调用一次文本模型，默认最多处理 60 个事件、并发不超过 2、单条总超时 45 秒；超额、未配置、超时、限流或返回无效时仅回退对应条目并显示中文原因。手动日报生成仍然只读，不会调用文本模型。MiniMax 只生成中文标题和中文文章概述，不能改变来源合法性、事件确认、证据根、收录范围或审核结论。

## Quality gates

```powershell
uv run ruff check .
uv run pytest
```

The current catalog spans professional media, first-party sources, social/community platforms,
aggregators/search, research/developer sources, newsletters/podcasts, and trend/business signals.
X and other restricted platforms are cataloged with explicit unlock requirements rather than
being silently omitted or scraped through high-risk methods.
