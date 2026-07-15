# Task 7 独立审查报告：中文热点页面与安全入队

审查范围：提交 `6e39c00..8f5b934`、Task 7 brief/完成报告，以及 v1.5 实施计划的 Task 7。审查仅覆盖 `codex/high-value-news-wave-v1-5` 工作树。

## 结论

**规格：不通过（1 个 P1）。代码质量：有条件通过。**

首页的“最近 24 小时已确认热点”“早期信号”“7 天趋势”确实全部从同一个已验证的 immutable operation snapshot 读取；详情链接也固定了 operation/version。`POST /events/update` 复用既有 loopback、same-origin 与一次性 token 边界，并且路由本身不创建 HTTP 客户端或 MiniMax 客户端。CLI 的 plan/status/report 路径也没有主动联网或调用模型。

但是，Task 7 新增的波次 Markdown 报告会直接输出 `HighValueWaveMemberRecord.conclusion`。这个字段可由抓取失败的 `result.error_message` 或异常 `str(error)` 写入。虽然报告调用了 `redact()`，该脱敏器并不能处理 `DATABASE_URL=...`、`MINIMAX_API_KEY=...`、`GITHUB_TOKEN=...` 等常见赋值形式。因此“报告对可能的凭据文本执行脱敏”的承诺不成立，不能在安全优先的收口分支中放行。

## 问题

### P1 — Wave 报告可泄露波次成员结论中的环境变量式凭据

- 位置：`src/newsradar/cli.py:250-257`（`waves report` 输出 `member.conclusion`）；`src/newsradar/waves/runtime.py:201-207`、`src/newsradar/waves/runtime.py:225-228`（将 `result.error_message` 与 `str(error)` 写入结论）；`src/newsradar/operations/logging.py:12-25`（`redact()` 规则）。
- `redact()` 只覆盖 Bearer、`Authorization:`、`Cookie:`、URL query key，以及 `api_key`/`token`/`password` 这几个通用字段；它不匹配 `DATABASE_URL=...`、`MINIMAX_API_KEY=...` 或 `GITHUB_TOKEN=...`。因此上游错误、代理诊断或异常文本一旦包含这些赋值，`newsradar waves report` 会把原文写入指定 Markdown 文件。
- 本审查以空环境显式调用 `redact()` 验证：上述三种字符串均保持原样，只有 `Authorization: Bearer ...` 被遮蔽。现有 `tests/test_cli.py` 只覆盖 `Authorization:`，遗漏了这三种变量式凭据。
- 修复方向：在持久化 wave member 结论前和渲染报告前均使用统一、保守的展示脱敏器；至少遮蔽 `*_API_KEY`、`*_TOKEN`、`*_SECRET`、`DATABASE_URL`/连接串和 bearer/cookie。对 Markdown 表格再删除或替换换行控制符。新增 CLI 回归测试，断言以上三种样本均不进入输出文件。

## 已核对的符合项

| 要求 | 证据与结论 |
| --- | --- |
| 首页三分区来自同一完整快照 | `EventQueryService.latest_operation_home()` 先调用 `latest_operation_page()`，随后仅对该 `page.events` 以 snapshot 的 `window_end` 切分 24 小时 confirmed、24 小时 emerging 与 7 天 trend。`latest_complete_event_snapshot()` 会验证 Wave member manifest、版本引用及评分记录。 |
| 不以全局 current 目录冒充运行结果 | 首页无完整快照时显示诊断提示；`/events` 默认同样走 `latest_operation_page()`，详情链接带 `operation` 与 `version`。 |
| 页面详情可解释 | 详情保留证据时间线、六项评分、原始链接和 MiniMax 降级标记；新增 trend、按官方/专业媒体/社区/聚合分类的来源角色以及缺失确认条件。 |
| `/events/update` 只创建波次任务 | 路由调用 `require_safe_action()`、加载本地 YAML/持久化 probe 冻结计划，并调用 `enqueue_high_value_wave()`；没有 `httpx`、抓取器或 MiniMax 调用。YAML 同步属于计划冻结的本地数据库写入，不是外部抓取。 |
| 写入边界 | 新路由使用既有 `require_loopback_host`、`require_same_origin` 和 `consume_one_time_token`；定向测试覆盖成功入队及 token 重用返回 400。 |
| CLI 不联网/不调用模型 | `waves enqueue` 只读取本地 YAML 和数据库 probe 快照；`status`/`report` 只读冻结的 operation/member。定向测试将 `httpx.AsyncClient` 替换为抛错对象，三条命令仍通过。 |
| 未建立并行产品 | 变更扩展既有 EventQueryService、`/events`/`/` 页面和 waves CLI；未创建新的新闻页面、Worker 或模型通道。 |

## 非阻断观察

- Task brief 提到详情应能说明“分歧”。现有页面会展示事件状态、分层原因和证据限制，但没有一个明确的“分歧/冲突说明”区块；对 `disputed` event 的解释仍主要依赖既有数据。建议在后续展示完善中补一条 `disputed` 回归测试和清晰的中文提示，但这不是本次 P1 的根因。
- 新路由的安全测试覆盖正常请求和 token 重用；跨域/非 loopback 的 helper 已有单测。可再增加对 `/events/update` 路由本身的跨域和远程 Host 集成断言，提升回归防护。

## 验证证据

```text
uv run pytest tests/web/test_high_value_wave_pages.py tests/web/test_event_routes.py tests/test_cli.py -q
53 passed

uv run ruff check src/newsradar/web src/newsradar/cli.py tests/web/test_high_value_wave_pages.py tests/test_cli.py
All checks passed!

git diff --check 6e39c00..HEAD
通过
```

以上测试和静态检查均通过，但无法覆盖此报告指出的凭据赋值形式泄露问题。

## P1 修复记录（2026-07-16）

已修复并复核。根因是统一 `redact()` 仅覆盖无前缀的 `api_key`、`token`、`password`，而 Wave 成员的 `conclusion` 会接收抓取错误文本后直接持久化。

- 扩展统一脱敏规则，覆盖 `DATABASE_URL`、`*_API_KEY`、`*_TOKEN`、`*_SECRET` 以及既有 Bearer/Authorization/Cookie/连接串规则；结构化日志中的 `DATABASE_URL` 字段同样直接隐藏。
- `WaveRepository.create_members()` 与 `finish_member()` 在写入结论前调用同一脱敏器；`waves report` 保留渲染前的第二道脱敏防线。
- 新增回归：使用合成的数据库 URL、MiniMax/GitHub/YouTube 键值和 Authorization 文本，断言原始值既不进入成员持久化记录，也不进入 Markdown；Authorization 以 `Authorization: [REDACTED]` 呈现。
- 未读取真实 `.env` 或环境变量值，未联网。

验证：

```text
uv run pytest tests/web/test_high_value_wave_pages.py tests/web/test_event_routes.py tests/test_cli.py tests/waves/test_repository.py tests/operations/test_logging.py -q
69 passed

uv run ruff check src/newsradar/operations/logging.py src/newsradar/waves/repository.py tests/test_cli.py tests/waves/test_repository.py tests/operations/test_logging.py
All checks passed!

git diff --check
passed
```
