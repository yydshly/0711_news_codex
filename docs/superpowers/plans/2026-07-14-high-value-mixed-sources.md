# News Codex 高价值混合来源波次实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 复用 News Codex 现有抓取与 Worker 体系，完成 Reddit、YouTube、Bluesky、Mastodon、Hacker News、Techmeme、GDELT、Google News 和专业媒体的具体目标扩展、真实抓取验证、中文网页展示与健康报告。

**Architecture:** 来源真相继续保存在严格 YAML 中，抓取继续由持久化 Worker 调用现有 Fetcher 完成；新增一个只读波次成员清单，让查询层从 Source、FetchRun、RawItem 聚合状态，不增加第二套抓取框架或重复状态表。网页和 Markdown 报告共用同一个波次查询结果，严格区分直接抓取、间接发现、凭据阻塞、降级、失败与未运行。

**Tech Stack:** Python 3.12、Pydantic 2、SQLAlchemy 2、PostgreSQL、HTTPX、feedparser、Typer、FastAPI、Jinja2、pytest、respx、Ruff。

## Global Constraints

- 暂不使用 Docker；在现有本机 Python 3.12 与 PostgreSQL 环境中执行。
- 不重做 Provider、Target、RawItem、Operation 或 Worker 架构。
- 不开发摘要、推荐、推送、网页雷达或新调度器。
- Reddit 只使用官方 OAuth，不回退 Cookie、登录网页或匿名 `.json`。
- YouTube 常规抓取使用频道上传播放列表，不使用 `search.list` 作为主路径。
- HTML 只允许来源级人工审核回退，本波次不新增自动 HTML 抓取。
- 社交与聚合来源只承担发现、互动或背景；事实确认仍需官方一手或独立专业媒体。
- MiniMax 不参与来源身份、合规、启用或验收决策；MiniMax 不可用不影响本波次。
- `.env`、API Key、OAuth Secret、Token 和 Cookie 不进入 YAML、数据库、报告、日志或前端。
- 所有新增中文页面文案和报告使用简体中文。

---

## 文件结构与职责

**新增文件：**

- `src/newsradar/sources/mixed_wave.py`：本波次 45 个具体目标的只读成员清单与分组，不包含运行状态。
- `src/newsradar/web/mixed_source_queries.py`：从现有 Source、FetchRun、RawItem 聚合波次状态与最近三轮结果。
- `src/newsradar/sources/mixed_wave_reporting.py`：把同一查询结果渲染为中文 Markdown。
- `src/newsradar/web/templates/mixed_sources.html`：现有网站中的中文波次总览。
- `tests/ingestion/test_high_value_mixed_catalog.py`：目录成员、角色、身份、接入方式与开关约束。
- `tests/web/test_mixed_source_queries.py`：状态分类、最近三轮与统计口径。
- `tests/web/test_mixed_sources_page.py`：路由、中文文案和下钻链接。
- `tests/test_mixed_wave_reporting.py`：报告结构与敏感信息排除。
- 新增 7 个 YouTube、6 个 Bluesky、4 个 Mastodon、4 个 Google News YAML 目标。

**修改文件：**

- `src/newsradar/ingestion/fetchers/youtube.py`：频道 → 上传播放列表 → 视频详情。
- `src/newsradar/ingestion/fetchers/base.py`：将 YouTube `channels` 端点路由到 YouTubeFetcher，并允许 Mastodon tag timeline。
- `src/newsradar/ingestion/fetchers/reddit.py`：删除作者与删除正文的数据最小化。
- `src/newsradar/ingestion/fetchers/mastodon.py`：允许经过 YAML 登记的 tag timeline。
- `src/newsradar/ingestion/fetchers/gdelt.py`：限制单次记录数并对异常响应给出稳定结果。
- `src/newsradar/cli.py`：增加 `newsradar sources mixed-report`。
- `src/newsradar/web/app.py`：增加 `/mixed-sources` 只读路由。
- `src/newsradar/web/templates/base.html`：增加“混合来源”导航入口。
- `src/newsradar/web/static/styles.css`：补充波次状态卡与三轮结果样式。
- `sources/universe/universe-youtube-1.yaml`：OpenAI YouTube 改为上传播放列表主路径。
- `sources/aggregators/google-news-ai.yaml`：明确模型与产品查询。
- `sources/aggregators/gdelt-ai.yaml`：缩小查询并限制返回量。
- 五个受限媒体的 `universe-*-2.yaml`：从 HTML 占位改为 Google News 间接发现。

---

### Task 1: 固定 45 个具体目标的波次契约与 YAML 目录

**Files:**
- Create: `src/newsradar/sources/mixed_wave.py`
- Create: `tests/ingestion/test_high_value_mixed_catalog.py`
- Create: `sources/video/anthropic-youtube.yaml`
- Create: `sources/video/google-deepmind-youtube.yaml`
- Create: `sources/video/nvidia-developer-youtube.yaml`
- Create: `sources/video/huggingface-youtube.yaml`
- Create: `sources/video/no-priors-youtube.yaml`
- Create: `sources/video/latent-space-youtube.yaml`
- Create: `sources/video/cognitive-revolution-youtube.yaml`
- Create: `sources/community/anthropic-bluesky.yaml`
- Create: `sources/community/huggingface-bluesky.yaml`
- Create: `sources/community/simon-willison-bluesky.yaml`
- Create: `sources/community/techcrunch-bluesky.yaml`
- Create: `sources/community/the-verge-bluesky.yaml`
- Create: `sources/community/mit-tech-review-bluesky.yaml`
- Create: `sources/community/mastodon-ai-tag.yaml`
- Create: `sources/community/mastodon-machinelearning-tag.yaml`
- Create: `sources/community/mastodon-llm-tag.yaml`
- Create: `sources/community/mastodon-artificialintelligence-tag.yaml`
- Create: `sources/aggregators/google-news-research.yaml`
- Create: `sources/aggregators/google-news-chips-compute.yaml`
- Create: `sources/aggregators/google-news-business.yaml`
- Create: `sources/aggregators/google-news-policy-safety.yaml`
- Modify: `sources/universe/universe-youtube-1.yaml`
- Modify: `sources/aggregators/google-news-ai.yaml`
- Modify: `sources/universe/universe-reuters-2.yaml`
- Modify: `sources/universe/universe-ap-2.yaml`
- Modify: `sources/universe/universe-bloomberg-2.yaml`
- Modify: `sources/universe/universe-financial-times-2.yaml`
- Modify: `sources/universe/universe-wsj-2.yaml`

**Interfaces:**
- Consumes: `load_source_tree(root: Path) -> list[SourceDefinition]`。
- Produces: `MIXED_WAVE_SOURCE_IDS: frozenset[str]`、`MIXED_WAVE_GROUPS: dict[str, tuple[str, ...]]`、`is_mixed_wave_source(source_id: str) -> bool`。

- [ ] **Step 1: 写目录契约失败测试**

```python
from pathlib import Path

from newsradar.sources.mixed_wave import MIXED_WAVE_GROUPS, MIXED_WAVE_SOURCE_IDS
from newsradar.sources.yaml_loader import load_source_tree


def test_high_value_mixed_wave_has_45_real_targets() -> None:
    sources = {source.id: source for source in load_source_tree(Path("sources"))}
    assert len(MIXED_WAVE_SOURCE_IDS) == 45
    assert MIXED_WAVE_SOURCE_IDS <= sources.keys()
    assert set(MIXED_WAVE_GROUPS) == {
        "reddit", "youtube", "bluesky", "mastodon", "hackernews",
        "techmeme", "gdelt", "google_news", "professional_media",
    }
    assert all(sources[source_id].research.status.value != "placeholder"
               for source_id in MIXED_WAVE_SOURCE_IDS)


def test_wave_roles_do_not_treat_social_or_aggregators_as_evidence() -> None:
    sources = {source.id: source for source in load_source_tree(Path("sources"))}
    for group in ("reddit", "bluesky", "mastodon", "techmeme", "gdelt", "google_news"):
        for source_id in MIXED_WAVE_GROUPS[group]:
            assert "evidence" not in {role.value for role in sources[source_id].roles}
```

- [ ] **Step 2: 运行测试并确认因成员模块或目标缺失而失败**

Run: `uv run pytest tests/ingestion/test_high_value_mixed_catalog.py -q`

Expected: FAIL，提示 `newsradar.sources.mixed_wave` 或新增 YAML 目标不存在。

- [ ] **Step 3: 写入精确波次成员清单**

```python
MIXED_WAVE_GROUPS = {
    "reddit": ("reddit-localllama", "reddit-machinelearning", "reddit-artificial"),
    "youtube": (
        "openai-youtube", "anthropic-youtube", "google-deepmind-youtube",
        "nvidia-developer-youtube", "huggingface-youtube", "no-priors-youtube",
        "latent-space-youtube", "cognitive-revolution-youtube",
    ),
    "bluesky": (
        "anthropic-bluesky", "huggingface-bluesky", "simon-willison-bluesky",
        "techcrunch-bluesky", "the-verge-bluesky", "mit-tech-review-bluesky",
    ),
    "mastodon": (
        "mastodon-ai-tag", "mastodon-machinelearning-tag", "mastodon-llm-tag",
        "mastodon-artificialintelligence-tag",
    ),
    "hackernews": ("hackernews-top", "hackernews-new", "hackernews-best"),
    "techmeme": ("techmeme-feed",),
    "gdelt": ("gdelt-ai",),
    "google_news": (
        "google-news-ai", "google-news-research", "google-news-chips-compute",
        "google-news-business", "google-news-policy-safety",
    ),
    "professional_media": (
        "universe-bbc-1", "universe-ars-technica-1", "universe-cnbc-1",
        "universe-techcrunch-1", "universe-the-verge-1", "universe-wired-1",
        "universe-guardian-1", "universe-mit-tech-review-1",
        "universe-venturebeat-1", "universe-reuters-2", "universe-ap-2",
        "universe-bloomberg-2", "universe-financial-times-2", "universe-wsj-2",
    ),
}
MIXED_WAVE_SOURCE_IDS = frozenset(
    source_id for source_ids in MIXED_WAVE_GROUPS.values() for source_id in source_ids
)


def is_mixed_wave_source(source_id: str) -> bool:
    return source_id in MIXED_WAVE_SOURCE_IDS
```

- [ ] **Step 4: 创建 YouTube、Bluesky、Mastodon 与 Google News 目标 YAML**

YouTube 必须使用以下已确认 Channel ID 与 uploads playlist：

| Source ID | Channel ID | Uploads playlist | 官方身份 |
|---|---|---|---|
| `openai-youtube` | `UCXZCJLdBC09xxGZ6gcdrc6A` | `UUXZCJLdBC09xxGZ6gcdrc6A` | `https://www.youtube.com/@OpenAI` |
| `anthropic-youtube` | `UCrDwWp7EBBv4NwvScIpBDOA` | `UUrDwWp7EBBv4NwvScIpBDOA` | `https://www.youtube.com/@anthropic-ai` |
| `google-deepmind-youtube` | `UCP7jMXSY2xbc3KCAE0MHQ-A` | `UUP7jMXSY2xbc3KCAE0MHQ-A` | `https://www.youtube.com/@GoogleDeepMind` |
| `nvidia-developer-youtube` | `UCBHcMCGaiJhv-ESTcWGJPcw` | `UUBHcMCGaiJhv-ESTcWGJPcw` | `https://www.youtube.com/@NVIDIADeveloper` |
| `huggingface-youtube` | `UCHlNU7kIZhRgSbhHvFoy72w` | `UUHlNU7kIZhRgSbhHvFoy72w` | `https://www.youtube.com/@HuggingFace` |
| `no-priors-youtube` | `UCSI7h9hydQ40K5MJHnCrQvw` | `UUSI7h9hydQ40K5MJHnCrQvw` | `https://www.youtube.com/@NoPriorsPodcast` |
| `latent-space-youtube` | `UCxBcwypKK-W3GHd_RZ9FZrQ` | `UUxBcwypKK-W3GHd_RZ9FZrQ` | `https://www.youtube.com/@LatentSpacePod` |
| `cognitive-revolution-youtube` | `UCjNRVMBVI30Sak_p6HRWhIA` | `UUjNRVMBVI30Sak_p6HRWhIA` | `https://www.youtube.com/@CognitiveRevolutionPodcast` |

每个 YouTube 主访问方式：

```yaml
- kind: rest_api
  url: https://www.googleapis.com/youtube/v3/channels
  priority: 1
  auth_envs: [YOUTUBE_API_KEY]
  params:
    id: UCrDwWp7EBBv4NwvScIpBDOA
- kind: atom
  url: https://www.youtube.com/feeds/videos.xml
  priority: 2
  params:
    channel_id: UCrDwWp7EBBv4NwvScIpBDOA
```

Bluesky 六个 actor 参数固定为：`anthropic.com`、`hf.co`、`simonwillison.net`、`techcrunch.com`、`theverge.com`、`technologyreview.com`。访问 URL 统一为 `https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed`。

Mastodon 四个 URL 固定为：

```text
https://mastodon.social/api/v1/timelines/tag/AI
https://mastodon.social/api/v1/timelines/tag/MachineLearning
https://mastodon.social/api/v1/timelines/tag/LLM
https://mastodon.social/api/v1/timelines/tag/ArtificialIntelligence
```

Google News 五类查询固定为：

```text
(AI OR LLM) (model OR product OR release) when:2d
(AI OR machine learning) (research OR paper OR benchmark) when:2d
(AI OR LLM) (GPU OR chip OR compute OR datacenter) when:2d
(AI OR LLM) (startup OR funding OR acquisition OR earnings) when:2d
(AI OR LLM) (policy OR safety OR copyright OR regulation) when:2d
```

所有查询同时配置 `hl=en-US`、`gl=US`、`ceid=US:en`。

新增目标统一使用以下完整字段契约；各组只替换上表或清单中明确给出的 `id`、`name`、`provider_id`、URL、参数和身份链接：

```yaml
status: candidate
language: en
topics: [artificial_intelligence, technology]
poll_interval_minutes: 30
expected_fields: [title, canonical_url, published_at]
reviewed_at: '2026-07-14'
unlock_requirements: []
ingestion:
  enabled: true
  approved_at: '2026-07-14'
  max_items_per_run: 20
research:
  status: needs_research
  purpose: 初步获取真实 AI/技术热点、讨论或媒体报道；深度来源审计在后续迭代完成。
  wanted_information: [title, canonical_url, published_at, author, engagement]
  conclusion: 已确认具体目标身份与可用入口，允许进入初步抓取；尚未标记为深度审计完成。
  risk_conclusion: 只使用已登记公开接口或官方 API，不使用登录 Cookie、验证码绕过或高风险网页抓取。
  reviewed_at: '2026-07-14'
```

各组固定差异：YouTube 使用 `nature: social`、`roles: [discovery, engagement, context]`、`authority_score: 4`、`availability: requires_credentials`；Bluesky 使用 `nature: social`、`roles: [discovery, engagement, context]`、`authority_score: 3`、`availability: ready`；Mastodon 使用 `nature: social`、`roles: [discovery, engagement]`、`authority_score: 2`、`availability: ready`；Google News 使用 `nature: aggregator`、`roles: [discovery]`、`authority_score: 2`、`availability: ready`、`coverage_mode: direct`。所有目标均记录对应平台官方文档和官方身份 URL 作为风险证据。

- [ ] **Step 5: 把五个受限媒体目标改为间接发现**

将 Reuters、AP、Bloomberg、Financial Times、WSJ 的 `universe-*-2` 改为：

```yaml
availability: ready
coverage_mode: indirect
roles: [discovery, context]
access_methods:
  - kind: rss
    url: https://news.google.com/rss/search
    priority: 1
    params:
      q: 'AI source:"Reuters" when:7d'
      hl: en-US
      gl: US
      ceid: US:en
ingestion:
  enabled: true
  approved_at: '2026-07-14'
research:
  status: needs_research
```

分别使用 `Reuters`、`Associated Press`、`Bloomberg`、`Financial Times`、`The Wall Street Journal` 作为发布者限定值。移除 HTML 主路径和凭据解锁要求，但保留“这是 Google News 间接发现，不代表媒体官方 API 已解锁”的中文说明。

- [ ] **Step 6: 校验目录并运行契约测试**

Run: `uv run newsradar sources validate --root sources`

Expected: `Validated` 且退出码为 0。

Run: `uv run pytest tests/ingestion/test_high_value_mixed_catalog.py -q`

Expected: PASS。

- [ ] **Step 7: 提交目录契约**

```bash
git add src/newsradar/sources/mixed_wave.py tests/ingestion/test_high_value_mixed_catalog.py sources
git commit -m "feat: define high-value mixed source cohort"
```

---

### Task 2: 将 YouTube 主路径改为上传播放列表

**Files:**
- Modify: `src/newsradar/ingestion/fetchers/youtube.py`
- Modify: `src/newsradar/ingestion/fetchers/base.py`
- Modify: `tests/ingestion/fetchers/test_youtube.py`

**Interfaces:**
- Consumes: `AccessMethod.params["id"]` 作为固定 Channel ID，`YOUTUBE_API_KEY` 由 `CredentialProvider.require` 提供。
- Produces: `YouTubeFetcher.fetch(...) -> FetchResult`，结果包含稳定 video ID、频道作者、发布时间和互动量。

- [ ] **Step 1: 写上传播放列表失败测试**

```python
@pytest.mark.asyncio
@respx.mock
async def test_youtube_uses_upload_playlist_instead_of_search() -> None:
    source = youtube_source(channel_id="channel-1")
    respx.get("https://www.googleapis.com/youtube/v3/channels").mock(
        return_value=httpx.Response(200, json={"items": [{"contentDetails": {
            "relatedPlaylists": {"uploads": "uploads-1"}}}]})
    )
    playlist = respx.get("https://www.googleapis.com/youtube/v3/playlistItems").mock(
        return_value=httpx.Response(200, json={"items": [
            {"contentDetails": {"videoId": "video-1"}}]})
    )
    respx.get("https://www.googleapis.com/youtube/v3/videos").mock(
        return_value=httpx.Response(200, json={"items": [video_fixture("video-1")]})
    )
    result = await fetch(source)
    assert result.outcome is FetchOutcome.SUCCEEDED
    assert result.items[0].external_id == "video-1"
    assert playlist.calls[0].request.url.params["playlistId"] == "uploads-1"
    assert not respx.calls or all(call.request.url.path != "/youtube/v3/search" for call in respx.calls)
```

- [ ] **Step 2: 运行测试确认旧搜索实现失败**

Run: `uv run pytest tests/ingestion/fetchers/test_youtube.py -q`

Expected: FAIL，旧代码请求 `/youtube/v3/search`。

- [ ] **Step 3: 实现三段式 API 调用**

```python
channel = await self.policy.get(
    "https://www.googleapis.com/youtube/v3/channels",
    params={"part": "contentDetails,snippet", "id": method.params["id"], "key": key},
)
uploads = channel.json()["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
playlist = await self.policy.get(
    "https://www.googleapis.com/youtube/v3/playlistItems",
    params={
        "part": "contentDetails", "playlistId": uploads,
        "maxResults": str(min(limit, 50)), "key": key,
    },
)
video_ids = [row["contentDetails"]["videoId"] for row in playlist.json().get("items", [])]
videos = await self.policy.get(
    "https://www.googleapis.com/youtube/v3/videos",
    params={"part": "snippet,statistics", "id": ",".join(video_ids), "key": key},
)
```

空频道返回 `FetchOutcome.SUCCEEDED` 和零条目；401/403 返回 `BLOCKED`，错误码分别为 `permission_required` 或 `quota_exhausted`；任何结果和异常不得包含 API Key。

- [ ] **Step 4: 更新 FetcherFactory 路由并覆盖空频道、403、备用 Atom**

```python
if host == "www.googleapis.com" and path == "/youtube/v3/channels":
    return YouTubeFetcher(self.policy, self.credentials or EnvironmentCredentials())
```

保留 Atom Feed 由 `RssFetcher` 处理；删除 `/youtube/v3/search` 的正式抓取路由，研究探测器不受影响。

- [ ] **Step 5: 运行 YouTube 与工厂测试**

Run: `uv run pytest tests/ingestion/fetchers/test_youtube.py tests/ingestion/test_eligibility.py tests/operations/test_fetch_runtime.py -q`

Expected: PASS。

- [ ] **Step 6: 提交 YouTube 主路径**

```bash
git add src/newsradar/ingestion/fetchers/youtube.py src/newsradar/ingestion/fetchers/base.py tests/ingestion/fetchers/test_youtube.py
git commit -m "feat: fetch YouTube channel uploads efficiently"
```

---

### Task 3: 补齐社交来源边界与删除数据处理

**Files:**
- Modify: `src/newsradar/ingestion/fetchers/mastodon.py`
- Modify: `src/newsradar/ingestion/fetchers/base.py`
- Modify: `src/newsradar/ingestion/fetchers/reddit.py`
- Modify: `tests/ingestion/fetchers/test_mastodon.py`
- Modify: `tests/ingestion/fetchers/test_reddit.py`

**Interfaces:**
- Consumes: 已审核 Mastodon `/api/v1/timelines/tag/<tag>` URL；Reddit OAuth listing row。
- Produces: tag timeline 的 `NormalizedRawItem`；删除作者不落作者字段，删除正文不落内容字段。

- [ ] **Step 1: 写 Mastodon tag 与 Reddit 删除数据失败测试**

```python
def test_mastodon_accepts_only_registered_tag_path() -> None:
    accepted = mastodon_source("/api/v1/timelines/tag/AI")
    rejected = mastodon_source("/api/v1/timelines/home")
    # accepted fetch succeeds; rejected raises unbounded_mastodon_discovery


def test_reddit_does_not_retain_deleted_author_or_body() -> None:
    item = RedditFetcher._item({
        "name": "t3_1", "title": "Deleted post",
        "permalink": "/r/test/comments/1/deleted/",
        "author": "[deleted]", "selftext": "[deleted]",
        "created_utc": 1, "score": 0, "num_comments": 0,
    })
    assert item is not None
    assert item.authors == ()
    assert item.content is None
    assert "[deleted]" not in str(item.raw_payload)
```

- [ ] **Step 2: 运行测试确认当前边界失败**

Run: `uv run pytest tests/ingestion/fetchers/test_mastodon.py tests/ingestion/fetchers/test_reddit.py -q`

Expected: FAIL，Mastodon 拒绝 tag path，Reddit raw payload 仍含删除标记。

- [ ] **Step 3: 允许严格 tag path 并保持同实例游标限制**

```python
is_tag_timeline = re.fullmatch(r"/api/v1/timelines/tag/[A-Za-z0-9_]+", parsed.path)
if not is_account_timeline and not is_local_timeline and not is_tag_timeline:
    raise ValueError("unbounded_mastodon_discovery")
```

游标验证继续要求 scheme、host、port 和 path 与登记目标一致；不得允许游标切换标签或实例。

- [ ] **Step 4: 清理 Reddit 删除数据**

```python
deleted_author = row.get("author") in {None, "[deleted]"}
deleted_body = row.get("selftext") in {None, "", "[deleted]", "[removed]"}
safe_payload = {
    key: value for key, value in row.items()
    if key not in {"access_token", "token", "selftext", "author"}
}
```

`authors=()` 用于删除作者；`content=None` 用于删除或移除正文；raw payload 不保存原作者和正文，只保留公开帖 ID、标题、永久链接、时间与互动量。

- [ ] **Step 5: 运行社交抓取器测试**

Run: `uv run pytest tests/ingestion/fetchers/test_mastodon.py tests/ingestion/fetchers/test_reddit.py tests/ingestion/fetchers/test_bluesky.py -q`

Expected: PASS。

- [ ] **Step 6: 提交社交边界修复**

```bash
git add src/newsradar/ingestion/fetchers/mastodon.py src/newsradar/ingestion/fetchers/base.py src/newsradar/ingestion/fetchers/reddit.py tests/ingestion/fetchers
git commit -m "feat: harden mixed social source ingestion"
```

---

### Task 4: 收紧 GDELT 与聚合来源归属

**Files:**
- Modify: `sources/aggregators/gdelt-ai.yaml`
- Modify: `src/newsradar/ingestion/fetchers/gdelt.py`
- Modify: `tests/ingestion/fetchers/test_gdelt.py`
- Modify: `tests/ingestion/fetchers/test_google_news.py`

**Interfaces:**
- Consumes: GDELT `articles` 响应、现有 `OriginResolver.resolve(url) -> Attribution`。
- Produces: 最多 50 条 discovery-only RawItem；未解析归属保留 `UNRESOLVED` 状态且不能进入证据角色。

- [ ] **Step 1: 写 GDELT 边界失败测试**

```python
@pytest.mark.asyncio
@respx.mock
async def test_gdelt_clamps_records_and_reports_invalid_payload() -> None:
    route = respx.get("https://api.gdeltproject.org/api/v2/doc/doc").mock(
        return_value=httpx.Response(200, json={"unexpected": []})
    )
    result = await fetch_gdelt(limit=100)
    assert route.calls[0].request.url.params["maxrecords"] == "50"
    assert result.outcome is FetchOutcome.PARTIAL
    assert result.error_code == "schema_drift"
```

- [ ] **Step 2: 运行 GDELT 与 Google News 测试确认失败**

Run: `uv run pytest tests/ingestion/fetchers/test_gdelt.py tests/ingestion/fetchers/test_google_news.py -q`

Expected: FAIL，当前 `maxrecords` 未限制且未知结构被当作零条成功。

- [ ] **Step 3: 实现记录上限与结构漂移结果**

```python
max_records = str(min(limit, 50))
payload = response.json()
if not isinstance(payload, dict) or not isinstance(payload.get("articles"), list):
    return response_result(
        response, outcome=FetchOutcome.PARTIAL,
        error_code="schema_drift", warnings=("missing_articles",),
    )
```

GDELT YAML 查询使用：

```yaml
params:
  query: '("artificial intelligence" OR "large language model") sourcelang:english'
  timespan: 2d
```

保持 GDELT `roles: [discovery]` 与 `ingestion.enabled: false`，真实三轮均成功后才在本分支人工改为 true；否则继续显示 `degraded`。

- [ ] **Step 4: 验证 Google News 始终保存发现地址与归属状态**

测试必须断言：`discovery_url` 保存 Google News 地址；`publisher_url` 只来自 `OriginResolver`；解析失败时 `origin_resolution_status == unresolved`，且来源角色不含 `evidence`。

- [ ] **Step 5: 运行聚合抓取测试**

Run: `uv run pytest tests/ingestion/fetchers/test_gdelt.py tests/ingestion/fetchers/test_google_news.py tests/ingestion/test_attribution.py -q`

Expected: PASS。

- [ ] **Step 6: 提交聚合来源修复**

```bash
git add sources/aggregators/gdelt-ai.yaml src/newsradar/ingestion/fetchers/gdelt.py tests/ingestion/fetchers/test_gdelt.py tests/ingestion/fetchers/test_google_news.py
git commit -m "feat: bound mixed aggregator discovery"
```

---

### Task 5: 建立波次查询与中文健康报告

**Files:**
- Create: `src/newsradar/web/mixed_source_queries.py`
- Create: `src/newsradar/sources/mixed_wave_reporting.py`
- Create: `tests/web/test_mixed_source_queries.py`
- Create: `tests/test_mixed_wave_reporting.py`
- Modify: `src/newsradar/cli.py`

**Interfaces:**
- Consumes: `MIXED_WAVE_GROUPS`、`SourceDefinitionRecord`、`FetchRunRecord`、`RawItemRecord`。
- Produces: `MixedSourceDashboard`、`MixedSourceQueryService.build() -> MixedSourceDashboard`、`render_mixed_wave_report(dashboard) -> str`、CLI `newsradar sources mixed-report`。

- [ ] **Step 1: 写状态分类与三轮失败测试**

```python
def test_mixed_wave_query_distinguishes_content_coverage() -> None:
    dashboard = MixedSourceQueryService(session).build()
    rows = {row.source_id: row for row in dashboard.targets}
    assert rows["direct"].state == "direct_ready"
    assert rows["indirect"].state == "indirect_ready"
    assert rows["reddit"].state == "blocked"
    assert rows["failed"].state == "failed"
    assert rows["never-run"].state == "not_run"
    assert rows["direct"].three_run_outcomes == ("succeeded", "no_change", "succeeded")
    assert rows["direct"].three_run_stable is True
```

- [ ] **Step 2: 运行查询测试确认模块缺失**

Run: `uv run pytest tests/web/test_mixed_source_queries.py -q`

Expected: FAIL，提示查询模块不存在。

- [ ] **Step 3: 实现只读聚合类型与状态优先级**

```python
class MixedSourceState(StrEnum):
    DIRECT_READY = "direct_ready"
    INDIRECT_READY = "indirect_ready"
    BLOCKED = "blocked"
    DEGRADED = "degraded"
    FAILED = "failed"
    NOT_RUN = "not_run"


def classify(source, latest_fetch) -> MixedSourceState:
    if source.availability != "ready" or (latest_fetch and latest_fetch.outcome == "blocked"):
        return MixedSourceState.BLOCKED
    if source.status == "degraded" or (latest_fetch and latest_fetch.outcome == "partial"):
        return MixedSourceState.DEGRADED
    if latest_fetch and latest_fetch.outcome == "failed":
        return MixedSourceState.FAILED
    if latest_fetch and latest_fetch.outcome in {"succeeded", "no_change"}:
        return (MixedSourceState.INDIRECT_READY
                if source.coverage_mode == "indirect"
                else MixedSourceState.DIRECT_READY)
    return MixedSourceState.NOT_RUN
```

每个目标仅查询最近三条完成 FetchRun；`three_run_stable` 要求恰好三条且全部属于 `succeeded/no_change`。RawItem 统计包括总数、最近发布时间和最新五条，不查询正文大字段。

- [ ] **Step 4: 实现中文 Markdown 报告与 CLI**

```python
@sources_app.command("mixed-report")
def mixed_source_report(
    output: Annotated[Path, typer.Option("--output")] = Path(
        "reports/high-value-mixed-sources.md"
    ),
) -> None:
    with create_session() as session:
        dashboard = MixedSourceQueryService(session).build()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_mixed_wave_report(dashboard), encoding="utf-8")
    typer.echo(f"已写入高价值混合来源报告：{output}")
```

报告包含：总体计数、九个来源组、每个具体目标、主要/备用方法、最近三轮、条目数、最新内容、中文结论和下步操作。报告不得出现 `YOUTUBE_API_KEY` 的值、OAuth Secret、Authorization、Cookie 或查询字符串中的凭据。

- [ ] **Step 5: 运行查询与报告测试**

Run: `uv run pytest tests/web/test_mixed_source_queries.py tests/test_mixed_wave_reporting.py tests/test_cli.py -q`

Expected: PASS。

- [ ] **Step 6: 提交查询与报告**

```bash
git add src/newsradar/web/mixed_source_queries.py src/newsradar/sources/mixed_wave_reporting.py src/newsradar/cli.py tests/web/test_mixed_source_queries.py tests/test_mixed_wave_reporting.py tests/test_cli.py
git commit -m "feat: report mixed source coverage"
```

---

### Task 6: 在现有网站增加中文混合来源视图

**Files:**
- Create: `src/newsradar/web/templates/mixed_sources.html`
- Create: `tests/web/test_mixed_sources_page.py`
- Modify: `src/newsradar/web/app.py`
- Modify: `src/newsradar/web/templates/base.html`
- Modify: `src/newsradar/web/static/styles.css`

**Interfaces:**
- Consumes: `MixedSourceQueryService(session).build()`。
- Produces: GET `/mixed-sources`，只读中文页面；链接复用 `/targets/{source_id}`、`/fetch-runs?source_id=...`、`/items?source_id=...`。

- [ ] **Step 1: 写页面失败测试**

```python
def test_mixed_sources_page_explains_real_coverage(client) -> None:
    response = client.get("/mixed-sources")
    assert response.status_code == 200
    assert "高价值混合来源" in response.text
    assert "直接抓取" in response.text
    assert "间接发现" in response.text
    assert "等待凭据" in response.text
    assert "最近三轮" in response.text
    assert "/targets/reddit-localllama" in response.text
    assert "API_KEY" not in response.text
```

- [ ] **Step 2: 运行页面测试确认 404**

Run: `uv run pytest tests/web/test_mixed_sources_page.py -q`

Expected: FAIL，`/mixed-sources` 返回 404。

- [ ] **Step 3: 增加只读路由与安全查询回退**

```python
@app.get("/mixed-sources", response_class=HTMLResponse)
def mixed_sources(request: Request) -> HTMLResponse:
    try:
        with create_session() as session:
            dashboard = MixedSourceQueryService(session).build()
    except (OperationalError, ProgrammingError) as error:
        return database_error_response(request, error)
    return templates.TemplateResponse(
        request=request,
        name="mixed_sources.html",
        context={"dashboard": dashboard, "database_status": "数据库已连接"},
    )
```

- [ ] **Step 4: 实现 A 风格中文页面**

页面顶部一句话解释：“这 45 个入口用于发现真实 AI/技术热点；社交和聚合负责发现，专业媒体负责确认。”

页面依次展示：

1. 六个状态计数卡。
2. 九个来源组及组内目标。
3. 每个目标的性质、直接/间接方法、最近三轮、条目数、最新时间。
4. 中文错误结论与操作建议。
5. 来源详情、抓取记录、原始条目三个下钻入口。

导航在现有 `base.html` 增加“混合来源”，不得创建第二套导航或应用壳。

- [ ] **Step 5: 运行页面、查询与无障碍基础测试**

Run: `uv run pytest tests/web/test_mixed_sources_page.py tests/web/test_mixed_source_queries.py tests/web -q`

Expected: PASS。

- [ ] **Step 6: 提交网页视图**

```bash
git add src/newsradar/web/app.py src/newsradar/web/templates/base.html src/newsradar/web/templates/mixed_sources.html src/newsradar/web/static/styles.css tests/web/test_mixed_sources_page.py
git commit -m "feat: show mixed source wave in Chinese UI"
```

---

### Task 7: 数据同步、三轮真实抓取、报告与最终审查

**Files:**
- Modify when evidence supports activation: `sources/aggregators/gdelt-ai.yaml`
- Create runtime artifact: `reports/high-value-mixed-sources.md`
- Create runtime artifact: `reports/high-value-mixed-sources-rounds.md`
- Test: full repository test suite

**Interfaces:**
- Consumes: 本机 `.env`、本机 PostgreSQL、现有 `newsradar serve/fetch/worker` 命令。
- Produces: 三轮 FetchRun 证据、中文健康报告、可供合并审查的干净代码提交。

- [ ] **Step 1: 在工作树准备被忽略的本机环境并同步目录**

```powershell
Copy-Item ..\..\.env .env
uv run newsradar providers sync --root providers
uv run newsradar sources sync --root sources
```

Expected: `.env` 仍被 Git 忽略；45 个波次目标均存在于数据库；同步重复运行不新增定义版本。

- [ ] **Step 2: 启动 Worker 并验证健康状态**

```powershell
uv run newsradar worker --help
uv run newsradar serve --host 127.0.0.1 --port 8767
```

使用现有后台启动方式运行服务；访问 `http://127.0.0.1:8767/system` 和 `/mixed-sources`，确认数据库与 Worker 正常。不得停止或覆盖主工作区正在使用的 8766 服务。

- [ ] **Step 3: 对开放来源连续运行三轮抓取**

每轮从已提交的波次成员清单展开开放目标，单目标最大五条：

```powershell
$sourceIds = uv run python -c "from newsradar.sources.mixed_wave import MIXED_WAVE_SOURCE_IDS; print('`n'.join(sorted(MIXED_WAVE_SOURCE_IDS - {'reddit-localllama','reddit-machinelearning','reddit-artificial','gdelt-ai'})))"
foreach ($round in 1..3) {
  foreach ($sourceId in ($sourceIds -split "`r?`n" | Where-Object { $_ })) {
    uv run newsradar fetch $sourceId --one-off --max-items 5 --wait
  }
  uv run newsradar fetch gdelt-ai --one-off --max-items 5 --wait
}
```

三轮之间不需要人为 sleep；每轮完成后记录 UTC 时间、operation ID、outcome、条目数和错误码到 `reports/high-value-mixed-sources-rounds.md`。

- [ ] **Step 4: 验证阻塞来源与失败隔离**

```powershell
uv run newsradar fetch reddit-localllama --one-off --max-items 5 --wait
uv run newsradar fetch reddit-machinelearning --one-off --max-items 5 --wait
uv run newsradar fetch reddit-artificial --one-off --max-items 5 --wait
```

无 Reddit 凭据时三者必须返回 `blocked/missing_credential`，其他来源抓取不受影响；若用户后来配置 OAuth，则改为验证真实内容、删除作者处理和速率限制。

- [ ] **Step 5: 根据三轮证据决定 GDELT 开关并生成报告**

只有 GDELT 三轮全部为 `succeeded/no_change`，且每轮没有 `schema_drift`，才修改为：

```yaml
status: candidate
ingestion:
  enabled: true
  approved_at: '2026-07-14'
```

否则保持 `status: degraded`、`ingestion.enabled: false`，并在报告中记录真实失败原因。

Run: `uv run newsradar sources mixed-report --output reports/high-value-mixed-sources.md`

Expected: 报告列出 45 个目标，计数与 `/mixed-sources` 一致。

- [ ] **Step 6: 浏览器验收现有网站中的波次入口**

验证：

- `/mixed-sources` 可从主导航进入。
- 九个来源组均显示。
- OpenAI/Anthropic YouTube 能下钻到真实视频 RawItem。
- Bluesky/Mastodon/HN 显示互动字段。
- Google News/Techmeme/GDELT 显示发现地址与原始媒体归属状态。
- Reddit 无凭据时显示中文解锁说明。
- 单个失败目标不让页面或整批抓取卡住。

- [ ] **Step 7: 执行完整自动化验证**

Run: `uv run ruff check .`

Expected: PASS。

Run: `uv run pytest -q`

Expected: 所有非环境跳过测试通过，0 failures。

Run: `git diff --check`

Expected: 无输出，退出码 0。

- [ ] **Step 8: 提交验收证据并进行合并前审查**

```bash
git add sources/aggregators/gdelt-ai.yaml reports/high-value-mixed-sources.md reports/high-value-mixed-sources-rounds.md
git commit -m "docs: record mixed source acceptance evidence"
```

审查重点：是否误把间接发现显示为直接覆盖、是否泄漏凭据、是否新增高风险回退、是否存在未受限网络调用、最近三轮统计是否只使用完成的 FetchRun。审查通过后再合并到 `main`，不强制推送、不删除主工作区未提交报告。

---

## 执行批次

为了快速推进而不牺牲审查边界，实际执行分为三个大批次：

1. **批次 A：来源与抓取能力** — Task 1–4，一次完成目录、YouTube、社交与聚合来源。
2. **批次 B：可观察性** — Task 5–6，一次完成查询、报告与中文网页。
3. **批次 C：真实验收与收口** — Task 7，完成同步、三轮抓取、浏览器验收、全量测试和代码审查。

每个批次结束报告结果和阻塞，不在批次内部为普通实现细节反复请求确认。
