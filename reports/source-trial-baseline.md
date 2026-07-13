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

## 全目录试用资格变化（历史评估口径）

27 个基线失败 Target 均完成具体候选登记；研究候选层得到 26 项成功、1 项 GDELT
HTTP 429 受限。随后执行内容探测与资格重算，历史评估新增 21 个可试用来源，使全目录
可试用数量从 16 增至 37。这 21 个来源曾通过 Worker 串行执行最多 5 条的第一版试用抓取，操作
209–229 全部 `succeeded`，单个来源没有阻塞后续来源。

新增来源为：`anthropic-sdk-releases`、`arxiv-cs-ai`、`arxiv-cs-dc`、
`arxiv-cs-se`、`bluesky-bsky`、`deepseek-v3-releases`、`google-ai-blog`、
`google-news-ai`、`hackernews-best`、`hackernews-new`、`hackernews-top`、
`mistral-common-releases`、`nvidia-developer-blog`、`openai-news`、
`openai-python-releases`、`techmeme-feed`、`universe-ai-snake-oil-1`、
`universe-ars-technica-1`、`universe-latent-space-1`、`universe-techcrunch-1`、
`universe-the-verge-1`。

本次 27 项固定批次中，有 8 项没有形成新的强绑定试用抓取证据。其中 Mistral Common
Releases 与 OpenAI Python SDK Releases 仍保留全目录历史试用资格，但本次因 GitHub
HTTP 403 未复验；其余 6 项当前未进入试用：GDELT（429）、DeepMind（85% degraded）、
Hugging Face（75% degraded）、Mastodon（43% degraded）、OpenAI YouTube（80%
degraded）和 Qwen3 Releases（本次 GitHub HTTP 403）。逐项证据见
`reports/source-failure-remediation.md`。

## 受控试用抓取

最初对修复后符合规则的 21 个公开直连来源完成了操作 209–229。为满足最终审查要求，
本轮又以“固定批次 → 候选探测 → 内容探测 → 试用抓取”的强绑定证据链重新验证其中
19 项；最终绑定内容探测 ID 的操作为 278–296，全部进入 `succeeded`，共接收 65 条、
写入 14 条 RawItem。
每项抓取均使用来源目录中已审核的 RSS、Atom 或公开 API，不使用登录 Cookie、浏览器
自动化、凭据回退或 HTML 自动抓取。

Mistral Common Releases 与 OpenAI Python SDK Releases 在本次候选复查时遇到 GitHub
HTTP 403 限额，因此没有把旧抓取记录冒充为新证据链结果，也没有自动重试。它们仍保留
先前内容探测形成的试用资格，但本批次结论明确显示“等待额度或权限复查”。

这 19 项结果是“本批强绑定受控试用抓取完成”的证据，不等于来源已经通过长期稳定性
审核，也不会自动把来源状态改成 `active`。其余 8 项的复查或阻塞结论见
`reports/source-failure-remediation.md`。

## 回归与页面验收

- 修复批次固定为 27 项，修复前可试用 16 项，修复后可试用 37 项。
- 上述 37 是全目录当前资格口径；本批次形成完整强绑定证据链的是 19 项。
- `/remediation` 仅展示固定批次，并显示原探测 ID、分类、候选方式、证据链和下一步。
- 页面与报告不展示 URL 查询参数、数据库连接串、认证头或 Cookie。
- 最终测试与浏览器验收结果以本批次收口后的命令输出为准。

## 结论

本批次已建立完整的 166 来源初探基线，并将 27 个失败来源冻结为独立修复批次。全目录
试用资格从 16 增加到 37；固定批次内有 19 项通过新的强绑定证据链完成试用抓取，另有
2 项仅保留历史资格但本次因 403 未复验，其余 6 项当前不可试用。后续仍需字段修复、
限流复查或稳定性审核。
