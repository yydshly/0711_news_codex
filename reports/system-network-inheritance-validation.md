# 系统网络继承验证报告

## 执行环境

- `HTTP_TRUST_ENV=true`（代码默认值；来源探测与抓取客户端均消费该设置）。
- 代理地址、VPN 节点、账号、Cookie 和环境变量值：未收集、未展示。
- 来源配置校验：通过（166 个来源）。
- 数据库迁移与持久化前置条件：未满足，错误分类为 `database_unavailable`；未启动、停止或修改既有服务。

## 来源探测结果

| 来源 | 方法 | 结果 | 样本数 | 说明 |
| --- | --- | --- | --- | --- |
| openai-youtube / youtube-atom | `research probe --persist` | 成功读取；持久化未执行 | 5 | 已读取公开 Atom 视频元数据；数据库不可用，未改变来源资格。 |
| openai-news | `probe --persist` | `database_unavailable` | 未记录 | 网络探测完成后持久化会话不可用；后续只读探测成功解析 5 条，状态仍为 `candidate`。 |
| arxiv-ai | `probe --persist` | `source_not_found` | 0 | 简报中的来源 ID 不存在；未升级任何来源。实际存在的 `arxiv-cs-ai` 只读探测成功解析 5 条，状态仍为 `candidate`。 |
| hacker-news-topstories | `probe --persist` | `source_not_found` | 0 | 简报中的来源 ID 不存在；未升级任何来源。实际存在的 `hackernews-top` 只读探测成功解析 5 条，状态仍为 `candidate`。 |

## Worker 抓取验收

| 任务 | 最终状态 | RawItem 数量 | 结论 |
| --- | --- | --- | --- |
| 单次开放来源抓取任务 | 验收前置条件未满足 | 未知 | 当前 CLI 不提供 `sources fetch` 子命令，且数据库不可用，不能排队、查询 operation 或验证 Worker 消费；未伪造抓取成功。 |

## 网页验收

- 本地服务端口可达；`/fetch-runs` 与 `/research` 均返回成功响应。
- 两页均包含中文系统网络状态文本；页面响应中未发现代理地址形式的值。
- 自动化浏览器运行时不可用，故未能进行人工浏览器可视化复核；上述仅为本地只读响应检查。

## 结论与限制

规则模式下每个域名是否可达取决于当时系统网络规则；本报告只陈述实际探测结果，不把失败归因到特定代理。开放来源的只读网络探测已证明系统网络继承路径可用，但数据库缺失使迁移、持久化和 Worker 端到端验收无法完成。简报所列两个来源 ID 和抓取 CLI 接口与当前工作树不一致，已如实记录，未以替代来源结果掩盖该限制。
