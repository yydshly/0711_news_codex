# 凭据来源长期启用设计

## 目标

将已经通过三轮真实抓取验证的 8 个凭据来源，从“候选 + 单次授权抓取”收口为可由 Worker 长期消费的来源。范围只包含 OpenAI YouTube 与 7 个 GitHub Release 目标，不新增来源、不增加摘要或推荐功能。

## 范围与来源

| 来源 | 平台 | 正式获取方式 | 所需凭据 |
| --- | --- | --- | --- |
| OpenAI YouTube | YouTube | YouTube Data API `search`（固定官方频道） | `YOUTUBE_API_KEY` |
| anthropic-sdk-releases | GitHub | GitHub Releases REST API | `GITHUB_TOKEN` |
| cuda-python-releases | GitHub | GitHub Releases REST API | `GITHUB_TOKEN` |
| deepseek-v3-releases | GitHub | GitHub Releases REST API | `GITHUB_TOKEN` |
| gemini-cli-releases | GitHub | GitHub Releases REST API | `GITHUB_TOKEN` |
| mistral-common-releases | GitHub | GitHub Releases REST API | `GITHUB_TOKEN` |
| openai-python-releases | GitHub | GitHub Releases REST API | `GITHUB_TOKEN` |
| transformers-releases | GitHub | GitHub Releases REST API | `GITHUB_TOKEN` |

三轮运行证据：操作 403–410、412–419、420–427 均以 `succeeded` 结束；没有新版本的 Release 返回 `no_change`，是去重后的正常成功结果。OpenAI YouTube 三轮分别插入 5、4、2 条内容。

## 配置与状态模型

每个来源保留其真实可用性：YouTube 是 `requires_credentials`，GitHub 的访问方式需要 `GITHUB_TOKEN`。这不是“公开可直接抓取”标记。

长期启用由 `ingestion.enabled: true` 和不可为空的 `approved_at` 表示。来源仍可显示为 `degraded`，因为“启用抓取”与“平台访问不需要凭据”是不同概念。状态说明将明确：凭据缺失或失效时，Worker 应生成可诊断的阻塞结果，不得回退到网页、Cookie 或其他非官方方式。

## 运行流程

1. CLI 或网页创建已批准来源的 `fetch` 操作。
2. Worker 选择来源首选官方 API；读取环境变量中的凭据，不保存或显示其内容。
3. 成功结果持久化 `fetch_runs` 与 `raw_items`；相同内容记为 `no_change` 或 unchanged，不视为失败。
4. 凭据不存在、401、403、429 或网络错误保留错误代码、可读中文建议和操作记录；单个来源失败不阻塞其他来源。
5. 中文健康报告根据最近运行记录展示三轮证据、当前状态和解锁要求。

## 安全边界

- API Key 和 Token 仅来自本地环境变量；YAML、数据库、报告、日志和网页都不得出现实际值。
- 仅使用官方 YouTube / GitHub API，不使用 Cookie、登录页抓取、代理绕过或第三方镜像。
- GitHub Token 应采用最小权限、设置过期时间；YouTube Key 应限制为 YouTube Data API v3，并在本机使用。
- 永久启用不代表无限抓取：现有 Worker 的队列、限流、重试、心跳与取消机制继续生效。

## 测试与验收

- 配置解析确认这 8 个来源已启用、审核日期存在且凭据要求不丢失。
- 无凭据时，抓取产生明确的 `blocked` 诊断且没有网页回退。
- 有凭据时，Worker 能成功持久化结果或正常给出 `no_change`。
- 报告同时区分“长期启用”“需要凭据”“最近三轮成功”和“无新内容”。
- 运行 ruff、完整 pytest、来源校验和关键 CLI / Worker 流程验证。

## 不在范围内

不修改 67 个平台/166 个目标的其他来源；不引入定时调度、网页摘要、推荐、邮件或推送。
