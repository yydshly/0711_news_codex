# 系统网络继承验证报告

## 执行环境

- `HTTP_TRUST_ENV=true`（代码默认值；来源探测与抓取客户端均消费该设置）。
- 代理地址、VPN 节点、账号、Cookie 和环境变量值：未收集、未展示。
- 证据时间均为 UTC；命令输出已脱敏，仅保留退出码、样本数和错误分类。
- 数据库迁移与持久化前置条件：未满足，错误分类为 `database_unavailable`；未启动、停止或修改既有服务。

## 可审计执行证据

| 时间（UTC） | 命令 | 退出码 | 关键结果 / 错误分类 | 样本数 |
| --- | --- | --- | --- | --- |
| 2026-07-13T08:26:04Z | `uv run newsradar sources validate --root sources` | 0 | 已校验 166 个来源 | 166 |
| 2026-07-13T08:26:06Z | `uv run newsradar sources research probe openai-youtube --candidate youtube-atom --limit 5 --persist` | 0 | 已读取公开 Atom 元数据；持久化未完成，`database_unavailable` | 5 |
| 2026-07-13T08:26:08Z | `uv run newsradar sources probe openai-news --persist` | 1 | `database_unavailable` | 未记录 |
| 2026-07-13T08:26:12Z | `uv run newsradar sources probe openai-news --no-persist` | 0 | 成功解析，完整度 100%，保持 `candidate` | 5 |
| 2026-07-13T08:26:16Z | `uv run newsradar sources probe arxiv-cs-ai --no-persist` | 0 | 成功解析，完整度 100%，保持 `candidate` | 5 |
| 2026-07-13T08:26:19Z | `uv run newsradar sources probe hackernews-top --no-persist` | 0 | 成功解析，完整度 100%，保持 `candidate` | 5 |
| 2026-07-13T08:26:41Z | `uv run newsradar sources probe arxiv-ai --persist` | 2 | `source_not_found` | 0 |
| 2026-07-13T08:26:42Z | `uv run newsradar sources probe hacker-news-topstories --persist` | 2 | `source_not_found` | 0 |
| 2026-07-13T08:26:44Z | 本地只读页面响应检查（`/fetch-runs`、`/research`） | 0 | 两页均为 200，包含中文网络状态文本，未发现代理地址形式的值 | 不适用 |

## 来源探测结果

| 来源 | 方法 | 结果 | 样本数 | 说明 |
| --- | --- | --- | --- | --- |
| openai-youtube / youtube-atom | `research probe --persist` | 成功读取；持久化未完成 | 5 | 公开 Atom 元数据可达；错误分类为 `database_unavailable`，未改变来源资格。 |
| openai-news（持久化） | `probe --persist` | `database_unavailable` | 未记录 | 持久化会话不可用；本记录不把网络解析结果记为成功。 |
| openai-news（只读） | `probe --no-persist` | 成功 | 5 | 独立的后续只读探测成功解析 5 条，完整度 100%，状态仍为 `candidate`。 |
| arxiv-ai | `probe --persist` | `source_not_found` | 0 | 简报中的来源 ID 不存在；未升级任何来源。 |
| arxiv-cs-ai | `probe --no-persist` | 成功 | 5 | 实际存在的开放来源；完整度 100%，状态仍为 `candidate`。 |
| hacker-news-topstories | `probe --persist` | `source_not_found` | 0 | 简报中的来源 ID 不存在；未升级任何来源。 |
| hackernews-top | `probe --no-persist` | 成功 | 5 | 实际存在的开放来源；完整度 100%，状态仍为 `candidate`。 |

## Worker 抓取验收

| 任务 | 最终状态 | RawItem 数量 | 结论 |
| --- | --- | --- | --- |
| 单次开放来源抓取任务 | 验收前置条件未满足 | 未知 | 当前 CLI 不提供 `sources fetch` 子命令，且数据库不可用，不能排队、查询 operation 或验证 Worker 消费；未伪造抓取成功。 |

## 网页验收

- 可审计证据见上表最后一行：本地 `/fetch-runs` 与 `/research` 均返回 200，且响应包含中文系统网络状态文本。
- 页面响应中未发现代理地址形式的值；未收集或展示任何代理、VPN、凭据或 Cookie。
- 自动化浏览器运行时不可用，故未能进行人工浏览器可视化复核；上述仅为本地只读响应检查。

## 结论与限制

规则模式下每个域名是否可达取决于当时系统网络规则；本报告只陈述实际探测结果，不把失败归因到特定代理。开放来源的只读网络探测已证明系统网络继承路径可用，但数据库缺失使迁移、持久化和 Worker 端到端验收无法完成。简报所列两个来源 ID 和抓取 CLI 接口与当前工作树不一致，已如实记录，未以替代来源结果掩盖该限制。
