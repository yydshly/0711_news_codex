# 来源覆盖收口 v1 验收报告

- 生成时间：2026-07-13T23:54:51.981365+00:00
- 口径：仅统计 availability=ready 且 coverage_mode=direct 的来源。
- 成功口径：FetchRun 为 succeeded 或 no_change。

## 执行前

| 范围内 | 已覆盖 | 可入队 | 阻塞 |
| ---: | ---: | ---: | ---: |
| 42 | 28 | 14 | 0 |

## 本轮操作

| 来源 ID | 操作 ID | 操作状态 | 最近抓取结果 | 错误码 | 可重试 | 本轮新增 RawItem | 下一步 |
| --- | ---: | --- | --- | --- | --- | ---: | --- |
| `arxiv-cs-cl` | 303 | succeeded | succeeded | — | — | 5 | 无需处理。 |
| `arxiv-cs-lg` | 304 | succeeded | succeeded | — | — | 5 | 无需处理。 |
| `cuda-python-releases` | 305 | succeeded | succeeded | — | — | 5 | 无需处理。 |
| `gemini-cli-releases` | 306 | succeeded | succeeded | — | — | 5 | 无需处理。 |
| `microsoft-research` | 307 | succeeded | succeeded | — | — | 5 | 无需处理。 |
| `openai-youtube` | 308 | succeeded | succeeded | — | — | 5 | 无需处理。 |
| `transformers-releases` | 309 | succeeded | succeeded | — | — | 5 | 无需处理。 |
| `universe-cnbc-1` | 310 | succeeded | succeeded | — | — | 5 | 无需处理。 |
| `universe-hard-fork-1` | 311 | succeeded | succeeded | — | — | 1 | 无需处理。 |
| `universe-import-ai-1` | 312 | succeeded | succeeded | — | — | 5 | 无需处理。 |
| `universe-interconnects-1` | 313 | succeeded | succeeded | — | — | 5 | 无需处理。 |
| `universe-mit-tech-review-1` | 314 | succeeded | succeeded | — | — | 5 | 无需处理。 |
| `universe-techmeme-1` | 315 | succeeded | succeeded | — | — | 5 | 无需处理。 |
| `universe-venturebeat-1` | 316 | succeeded | succeeded | — | — | 5 | 无需处理。 |

## 基线 15 项逐项结论

| 来源 ID | 执行前探测/资格 | 操作证据 | FetchRun 证据 | 本轮新增 RawItem | 最终结论 |
| --- | --- | --- | --- | ---: | --- |
| `arxiv-cs-cl` | 可入队：可试用抓取：公开直连且首次探测合格 | 操作 303：succeeded | succeeded | 5 | 已覆盖：已有 succeeded/no_change 抓取证据。 |
| `arxiv-cs-lg` | 可入队：可试用抓取：公开直连且首次探测合格 | 操作 304：succeeded | succeeded | 5 | 已覆盖：已有 succeeded/no_change 抓取证据。 |
| `cuda-python-releases` | 可入队：可试用抓取：公开直连且首次探测合格 | 操作 305：succeeded | succeeded | 5 | 已覆盖：已有 succeeded/no_change 抓取证据。 |
| `gemini-cli-releases` | 可入队：可试用抓取：公开直连且首次探测合格 | 操作 306：succeeded | succeeded | 5 | 已覆盖：已有 succeeded/no_change 抓取证据。 |
| `microsoft-research` | 可入队：可试用抓取：公开直连且首次探测合格 | 操作 307：succeeded | succeeded | 5 | 已覆盖：已有 succeeded/no_change 抓取证据。 |
| `openai-youtube` | 可入队：可试用抓取：公开直连且首次探测合格 | 操作 308：succeeded | succeeded | 5 | 已覆盖：已有 succeeded/no_change 抓取证据。 |
| `qwen3-releases` | 官方 Releases 端点当前没有条目，HTTP 200 空数组不算内容覆盖。 | 未创建操作 | 尚无 FetchRun | 0 | 退出就绪直连统计 |
| `transformers-releases` | 可入队：可试用抓取：公开直连且首次探测合格 | 操作 309：succeeded | succeeded | 5 | 已覆盖：已有 succeeded/no_change 抓取证据。 |
| `universe-cnbc-1` | 可入队：可试用抓取：公开直连且首次探测合格 | 操作 310：succeeded | succeeded | 5 | 已覆盖：已有 succeeded/no_change 抓取证据。 |
| `universe-hard-fork-1` | 可入队：可试用抓取：公开直连且首次探测合格 | 操作 311：succeeded | succeeded | 1 | 已覆盖：已有 succeeded/no_change 抓取证据。 |
| `universe-import-ai-1` | 可入队：可试用抓取：公开直连且首次探测合格 | 操作 312：succeeded | succeeded | 5 | 已覆盖：已有 succeeded/no_change 抓取证据。 |
| `universe-interconnects-1` | 可入队：可试用抓取：公开直连且首次探测合格 | 操作 313：succeeded | succeeded | 5 | 已覆盖：已有 succeeded/no_change 抓取证据。 |
| `universe-mit-tech-review-1` | 可入队：可试用抓取：公开直连且首次探测合格 | 操作 314：succeeded | succeeded | 5 | 已覆盖：已有 succeeded/no_change 抓取证据。 |
| `universe-techmeme-1` | 可入队：可试用抓取：公开直连且首次探测合格 | 操作 315：succeeded | succeeded | 5 | 已覆盖：已有 succeeded/no_change 抓取证据。 |
| `universe-venturebeat-1` | 可入队：可试用抓取：公开直连且首次探测合格 | 操作 316：succeeded | succeeded | 5 | 已覆盖：已有 succeeded/no_change 抓取证据。 |

## 执行后

| 范围内 | 已覆盖 | 可入队 | 阻塞 |
| ---: | ---: | ---: | ---: |
| 42 | 42 | 0 | 0 |

## 仍未收口的来源

| 来源 ID | 稳定原因码 | 中文说明 |
| --- | --- | --- |
| 无 | — | 当前范围内来源均已有成功抓取证据。 |

## 两项目录口径修正

- OpenAI YouTube：Atom 负责公开发现；engagement 由需 Key 的 Data API 补充，不阻塞 Atom。
- Qwen3 Releases：当前无 Release 条目，退出 ready 统计；满足解锁条件后重新探测。

## 安全声明

- 本轮未使用 Cookie、浏览器会话、代理绕过或 MiniMax 决策。

## 结论

当前 ready + direct 范围内来源均已留下成功抓取证据。
