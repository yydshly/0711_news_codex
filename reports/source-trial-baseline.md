# 来源全量初探与试用基线

## 执行范围与口径

本报告记录 2026-07-13 的一次真实批量初探。依次完成了 Provider/Source
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
| 试用可抓取 | 16 |
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
| 可试用抓取 | 16 | 无 | 仅在受控试用操作中继续使用；仍需后续稳定性审计。 |
| 仅目录收录 | 65 | `catalog_only`：仅保留目录/发现价值，不提供试用抓取。 | 获得并审计合规的公开直连自动访问方式后，单独评估覆盖模式。 |
| 仅发现 | 53 | `discovery_only`：间接来源只用于发现线索，需回溯原始来源。 | 为可公开访问的原始来源建立独立、可审计的 direct Target，再重新探测。 |
| 当前未就绪 | 5 | `not_ready`：需要凭据、审批或其他就绪条件。 | 在获得授权且完成访问方式审计后，再进行独立受控探测；不在本批次重试。 |
| 探测未成功 | 27 | `probe_not_successful`：本次连接、HTTP 或解析结果未成功。 | 保留本次失败证据；待网络/端点条件变更后按独立审计流程复测。 |

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

## 受控试用抓取

选择已合格的公开 RSS 来源 `microsoft-research`，实际执行：

```powershell
newsradar fetch --trial microsoft-research --max-items 5 --wait
```

命令排出 1 个试用候选并创建操作 143。该操作最终状态为 `partial`，结果为
`blocked`，错误代码为 `not_approved`，`items_received = 0`、`items_inserted = 0`，
且该来源的 RawItem 记录数为 0。因此本次没有满足“operation 为 succeeded/partial
且 RawItem 存在”的成功验收条件；已在该失败点停止，未用 one-off、网页登录或重试
替代。

## 回归与页面验收

- `pytest -q`：发现 1 项失败、其余通过。失败为
  `tests/web/test_ingestion_pages.py::test_fetch_action_enqueues_once_and_never_fetches_in_request`：
  断言仍期待普通 fetch 的 `requested_scope` 不含 `trial: false`，而当前实现已持久化该
  默认字段。此项不在本任务允许修改范围内。
- `ruff check src tests migrations`：通过。
- 未发现监听于 8000、8080 或 3000 端口的本地 Web 服务，故使用实际数据库的
  FastAPI TestClient 验收。`/` 与 `/targets` 均返回 HTTP 200，且页面不含
  `DATABASE_URL`、`Authorization` 或 `Cookie`。但所需中文试用指标/说明文本未以正常
  中文匹配到（页面模板内容呈现为乱码），因此“中文四类指标、试用解释、间接回溯提示、
  受限解锁说明可见”的视觉验收未通过；本任务未改动页面实现。

## 结论

本批次已建立完整的 166 来源初探基线，识别出 16 个符合规则的受控试用候选。实际 RSS
试用操作被 `not_approved` 阻断且未产生 RawItem；应在后续获得相应运行时批准条件并修复
页面编码与回归断言后，再进行新的、独立记录的受控试用。
