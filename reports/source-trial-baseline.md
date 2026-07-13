# 来源全量初探与试用基线

## 执行范围与口径

本报告记录 2026-07-13 的一次真实批量初探，以及同日完成的 27 项失败来源修复批次。依次完成了 Provider/Source
校验、同步和 `sources probe --all --persist`；每个来源仅使用该批次的最新已完成
探测记录判定试用资格，未为改善结果重试受限或失败来源。所有数字均由持久化数据库
中的本次探测结果和来源定义汇总得出；未记录请求头、密钥、Cookie、代理或连接串。

“试用可抓取”仅表示公开直连来源在首次探测中字段合格，不表示长期稳定、长期启用
或事实确认。

## 汇总

| 指标 | 数量 |
| --- | ---: |
| Target 总数 | 166 |
| 已探索（有最新完成探测） | 166 |
| 修复前试用可抓取 | 16 |
| 修复后试用可抓取 | 37 |
| 仅发现 | 53 |
| 受限目录 | 70 |

### 来源性质分布

| 类别 | 数量 |
| --- | ---: |
| 官方/第一方 | 24 |
| 专业媒体 | 62 |
| 研究 | 19 |
| 社区 | 6 |
| 聚合 | 25 |
| 社交 | 30 |

### 试用判定结果

| 判定 | 数量 | 当前阻塞原因 | 后续解锁步骤 |
| --- | ---: | --- | --- |
| 可试用抓取 | 37 | 无 | 仅在受控试用操作中继续使用；仍需后续稳定性审计。 |
| 仅目录收录 | 65 | `catalog_only`：仅保留目录/发现价值，不提供试用抓取。 | 获得并审计合规的公开直连自动访问方式后，单独评估覆盖模式。 |
| 仅发现 | 53 | `discovery_only`：间接来源只用于发现线索，需回溯原始来源。 | 为可公开访问的原始来源建立独立、可审计的 direct Target，再重新探测。 |
| 当前未就绪 | 5 | `not_ready`：需要凭据、审批或其他就绪条件。 | 在获得授权且完成访问方式审计后，再进行独立受控探测；不在本批次重试。 |
| 探测未成功 | 6 | `probe_not_successful`：最新内容探测仍为受限、字段不足或没有样本。 | 保留真实证据；满足复查窗口或字段条件后再按独立审计流程复测。 |

受限目录数量按产品口径计算：`availability != ready` 或 `coverage_mode = catalog_only`，
故与试用判定表不是互斥分区以外的额外来源。

## 已合格的试用来源

风险结论中的分值为来源定义的总风险；所有条目均为“首次探测合格”，仍限单次、
有界的受控试用。

| ID | 名称 | 访问方式 | 完整度 | 样本数 | 探测时间（UTC） | 风险结论 |
| --- | --- | --- | ---: | ---: | --- | --- |
| `cuda-python-releases` | NVIDIA CUDA Python Releases | REST API | 100% | 5 | 2026-07-13 11:46:55Z | 总风险 4；可受控试用。 |
| `gemini-cli-releases` | Gemini CLI Releases | REST API | 100% | 5 | 2026-07-13 11:46:54Z | 总风险 4；可受控试用。 |
| `transformers-releases` | Hugging Face Transformers Releases | REST API | 100% | 5 | 2026-07-13 11:46:56Z | 总风险 4；可受控试用。 |
| `microsoft-research` | Microsoft Research | RSS | 100% | 5 | 2026-07-13 11:46:55Z | 总风险 3；可受控试用。 |
| `arxiv-cs-cl` | arXiv cs.CL | Atom | 100% | 5 | 2026-07-13 11:46:54Z | 总风险 4；可受控试用。 |
| `arxiv-cs-lg` | arXiv cs.LG | Atom | 100% | 5 | 2026-07-13 11:46:54Z | 总风险 4；可受控试用。 |
| `universe-bbc-1` | BBC Technology primary | RSS | 100% | 5 | 2026-07-13 11:46:54Z | 总风险 4；可受控试用。 |
| `universe-cnbc-1` | CNBC Technology primary | RSS | 100% | 5 | 2026-07-13 11:46:54Z | 总风险 4；可受控试用。 |
| `universe-guardian-1` | The Guardian Technology primary | RSS | 100% | 5 | 2026-07-13 11:46:55Z | 总风险 8；可受控试用，注意较高定义风险。 |
| `universe-hard-fork-1` | Hard Fork primary | RSS | 100% | 5 | 2026-07-13 11:46:56Z | 总风险 6；可受控试用。 |
| `universe-import-ai-1` | Import AI primary | RSS | 100% | 5 | 2026-07-13 11:46:54Z | 总风险 4；可受控试用。 |
| `universe-interconnects-1` | Interconnects primary | RSS | 100% | 5 | 2026-07-13 11:46:54Z | 总风险 4；可受控试用。 |
| `universe-mit-tech-review-1` | MIT Technology Review primary | RSS | 100% | 5 | 2026-07-13 11:46:54Z | 总风险 4；可受控试用。 |
| `universe-techmeme-1` | Techmeme primary | RSS | 100% | 5 | 2026-07-13 11:46:55Z | 总风险 6；可受控试用。 |
| `universe-venturebeat-1` | VentureBeat primary | RSS | 100% | 5 | 2026-07-13 11:46:54Z | 总风险 4；可受控试用。 |
| `universe-wired-1` | WIRED primary | RSS | 100% | 5 | 2026-07-13 11:46:54Z | 总风险 4；可受控试用。 |

## 修复批次新增的 21 个试用来源

27 个基线失败 Target 均完成具体候选登记；研究候选层得到 26 项成功、1 项 GDELT
HTTP 429 受限。随后执行内容探测与资格重算，新增 21 个可试用来源，使全目录可试用
数量从 16 增至 37。21 个来源均通过 Worker 串行执行最多 5 条的试用抓取，操作
209–229 全部 `succeeded`，单个来源没有阻塞后续来源。

新增来源为：`anthropic-sdk-releases`、`arxiv-cs-ai`、`arxiv-cs-dc`、
`arxiv-cs-se`、`bluesky-bsky`、`deepseek-v3-releases`、`google-ai-blog`、
`google-news-ai`、`hackernews-best`、`hackernews-new`、`hackernews-top`、
`mistral-common-releases`、`nvidia-developer-blog`、`openai-news`、
`openai-python-releases`、`techmeme-feed`、`universe-ai-snake-oil-1`、
`universe-ars-technica-1`、`universe-latent-space-1`、`universe-techcrunch-1`、
`universe-the-verge-1`。

仍未进入试用的 6 项为：GDELT（429）、DeepMind（85% degraded）、Hugging Face
（75% degraded）、Mastodon（43% degraded）、OpenAI YouTube（80% degraded）和
Qwen3 Releases（当前 0 条 Release）。逐项样本、字段、试用和抓取结论见
`reports/source-failure-remediation.md`。

## 受控试用抓取

首次尝试使用 `microsoft-research`（操作 143）时，被旧根检出的 Worker 消费；该旧
Worker 不含试用实现，操作以 `partial` / `not_approved` 结束，未创建 RawItem。该结果
未作为试用资格或抓取能力的判断依据，也没有重试该来源。

随后仅暂停精确匹配 `worker --forever --worker-id main-runtime-owner` 的旧 Worker，以当前
worktree 启动临时、隐藏的 `source-trial-validation` Worker，并选择另一条已合格的公开 RSS
来源 `universe-bbc-1`，实际执行：

```powershell
newsradar fetch --trial universe-bbc-1 --max-items 5 --wait
```

命令排出 1 个试用候选并创建操作 144。该操作由 `source-trial-validation` Worker 的尝试
记录消费，最终状态为 `succeeded`，无错误代码，`fetch_run_id = 244`，
`items_received = 5`、`items_inserted = 1`；该 fetch run 新建 1 条 RawItem（来源现有
RawItem 总数为 6）。临时 Worker 已停止，原 `main-runtime-owner` Worker 已按原根目录命令
恢复。没有使用 one-off 或网页登录替代。

## 回归与页面验收

- `pytest -q`：通过。
- `ruff check src tests migrations`：通过。
- 未发现监听于 8000、8080 或 3000 端口的本地 Web 服务，故使用实际数据库的
  FastAPI TestClient 验收。`/` 与 `/targets` 均返回 HTTP 200，中文四类指标、试用解释、
  间接回溯提示与受限解锁说明均可见，且页面不含 `DATABASE_URL`、`Authorization` 或
  `Cookie`。

## 结论

本批次已建立完整的 166 来源初探基线，识别出 16 个符合规则的受控试用候选。实际 RSS
试用操作 144 已由当前 worktree 的临时 Worker 成功完成并持久化 RawItem；该结果仅构成
首次受控试用证据，后续仍需稳定性审计后再决定长期启用。
