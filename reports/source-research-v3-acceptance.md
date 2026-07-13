# 来源研究 v3 验收报告

## 结论

本轮在 `codex/source-research-v3` 分支、基线提交
`f6b03cce90f2312b782f85de45f4d91e7a69329d` 上完成来源研究 v3 的真实探测与离线验收。
目录校验无错误，当前共 67 个 Provider、166 个 Target，其中 34 个是真实 Target、132 个为
占位 Target；1 个已验证、33 个待研究。占位、重复、能力探测和凭据阻塞均未计作内容覆盖。

本轮 MiniMax **未调用**，没有生成摘要、推荐或正式新闻内容，也没有读取其他工作树的凭据。

## 状态口径

- **成功**：获得公开响应和有界样本。
- **部分成功**：只确认部分字段或人工元数据边界，不代表正式内容覆盖。
- **凭据阻塞**：缺少官方 Key、OAuth、审批或付费条件，且没有网页回退。
- **失败**：网络或实现错误导致本轮没有可用结果。
- **未运行**：环境或凭据前置条件不满足，明确保留为后续动作。

## 真实网络探测

探测时间为 2026-07-13 UTC。所有请求均使用有界超时，不使用代理、Cookie、验证码、浏览器
登录态或反爬绕过；最多保留五条脱敏元数据样本。

| 对象 | 路径 | 结果 | 样本 | 事实与边界 |
| --- | --- | --- | ---: | --- |
| OpenAI YouTube | 官方 Atom | 成功 | 5 | 读取视频 ID、标题、频道和发布时间；修复 CLI 安全客户端路径后复测成功。 |
| OpenAI YouTube | Data API（无 Key） | 凭据阻塞 | 0 | `missing_credential`；未发起网页回退。带 Key 详情探测未运行。 |
| OpenAI YouTube 视频 `MdTqoR-7oHg` | `youtube-transcript-api` | 成功 | 1 | 临时无 Cookie 会话读取有界文字样本；第三方库不是官方 API。 |
| OpenAI News | RSS | 成功 | 3 | HTTP 200；标题、URL、发布时间和摘要字段齐全。 |
| OpenAI | Sitemap | 成功 | 3 | HTTP 200；取得 URL，缺少发布时间；robots 允许不等于条款批准。 |
| Hugging Face 文章 | 静态 HTML | 阻塞（修复前实测） | 0 | HTTP 200，但页面中的挑战脚本词触发旧规则；规则已收窄，按验收停止条件未再次请求，因此不声称成功。 |
| OpenAI 文章 | 静态 HTML | 阻塞 | 0 | HTTP 403；未重试登录态、代理或浏览器路径。 |
| Mastodon 官方账号 | 公开 API | 成功 | 5 | HTTP 200；取得公开状态 URL 和互动字段，仅作发现/互动信号。 |
| X | 官方能力目录 | 凭据阻塞 | 0 | `requires_payment`；需要官方付费访问。 |
| LinkedIn | 官方能力目录 | 凭据阻塞 | 0 | `requires_approval`；需要官方权限审批。 |
| TikTok | Research API 能力目录 | 凭据阻塞 | 0 | `requires_approval`；需要官方研究权限。 |
| yt-dlp | 人工元数据边界 | 部分成功 | 0 | 目录记录版本/许可证/维护用途；媒体下载未运行。 |

OpenAI Atom 首次 CLI 探测曾返回 `HTTPStatusError`，而相同 URL 的直接请求为 HTTP 200。
定位到 CLI 为 YouTube 单独创建了未使用统一请求头的客户端；改用统一安全研究工厂后，真实复测
取得五条样本。该首次结果按**失败**保留在本报告中，没有被隐藏。

## 本轮发现并修复的问题

1. Task 7 的 `app.py`、`queries.py` 存在 31 项 Ruff 格式错误；仅重排格式和导入，网页测试
   行为保持不变。
2. YouTube CLI 绕过统一安全研究客户端，导致真实 Atom 响应不稳定；现已统一走 Probe Factory。
3. 通用 URL 脱敏会删除 YouTube `?v=`，导致样本失去视频身份；改为无查询参数的
   `https://youtu.be/<video-id>`。
4. YouTube 结果未填充 `sample_count`；现复用统一结果构造器。
5. robots 响应的 `Set-Cookie` 会污染客户端并阻塞 Sitemap/HTML 第二次请求；现在立即丢弃
   服务端 Cookie，且独立请求始终不发送 Cookie。
6. RSS/API 正文中正常出现 “verify” 或 “sign in” 会被误判为登录墙；结构化协议不再扫描
   正文关键词，HTML 只匹配明确挑战短语。
7. 字幕协程超时原先仍可能在 CLI 关闭默认线程池时等待阻塞调用；现在使用守护线程执行，
   requests 会话同时设置连接/读取超时，子进程回归测试证明超时后 CLI 可及时退出。

以上修复均先增加失败测试，再实现最小修复。

## 目录和网页验收

目录命令执行成功：

```powershell
uv run newsradar sources research validate --root sources --provider-root providers
uv run newsradar sources research report --root sources --provider-root providers `
  --output reports/source-research-v3-matrix.md
```

结果为 34 个真实 Target、0 个错误。报告仍包含大量 `generic_platform_target`、
`placeholder_target` 和 `duplicate_candidate` 警告，这些是待继续研究的覆盖缺口，不是已验证
内容来源。完整矩阵见 `reports/source-research-v3-matrix.md`。

中文网页 `/research` 和 `/research/targets/<source-id>` 的离线路由测试通过。当前工作树没有
`.env`，本机数据库连接不可用时页面返回中文 503，不泄漏堆栈；本轮未伪造数据库内探测历史。

## 离线门禁与迁移状态

已执行：

```text
uv run pytest -q
uv run ruff check src tests migrations
git diff --check
uv run alembic current
```

- 最终全量测试退出码为 0，3 项依赖本地 PostgreSQL 的验收测试按环境条件跳过；新增
  Task 8 验收测试 4 项全部通过。
- Ruff 从 31 项错误修复为 0 项，最终 `ruff check src tests migrations` 通过。
- `git diff --check` 通过；`.superpowers` 的既有未跟踪文件不属于本次提交。
- `alembic current` 在 30 秒内未能连接数据库并超时。由于本工作树没有 `.env`，迁移头
  `20260712_0009` 的在线 `current/check` **未运行完成**，不得写成已通过。

提交前已重新执行全量测试、Ruff、目录校验和差异检查；除上述 PostgreSQL 环境阻塞外均通过。

## 已知限制与下一步

- 166 个 Target 不等于 166 个真实可读来源；当前只有 1 个 `verified`。
- 静态 HTML 仍需逐来源条款、robots、结构和挑战页面复核；本轮两个文章样本均为阻塞。
- YouTube Data API 带 Key 探测未运行；如提供 Key，应限制到 YouTube Data API、设置配额并可
  随时撤销。
- X、LinkedIn、TikTok 只有能力和解锁条件记录，不具备本轮直接内容覆盖。
- PostgreSQL 恢复后需执行 `uv run alembic current`、`uv run alembic check`，同步目录并在
  浏览器复核真实数据页。
- 本地个人版只探测经 Git/YAML 人工审核的 HTTPS 主机名；本阶段拒绝字面私网 IP、敏感查询、
  Cookie、环境代理并逐跳复核重定向，但不实现 DNS rebinding 或 pinned-IP。该边界不适用于
  接收外部用户任意 URL 的公开服务，若未来开放输入必须重新设计。
- 后续应优先把 33 个 `needs_research` Target 逐项补足候选方式和样本，而不是进入摘要、推荐
  或继续增加占位来源。
