# 来源重复占位项收口验收报告

日期：2026-07-14

## 本次处理范围

处理了 19 组早期批量目录记录，共 38 条：Anthropic、arXiv、Bluesky、GDELT、GitHub、Google AI、Google News、Hacker News、Hugging Face Daily Papers、Mastodon、npm、NVIDIA、OpenAI、OpenReview、Polymarket、PyPI、SEC EDGAR、Semantic Scholar 和 The Batch。

每组均保留两个既有 ID：

- `universe-<provider>-1`：研究状态为 `duplicate`，作为审计历史保留，不参与探测或抓取。
- `universe-<provider>-2`：研究状态为 `needs_research`，作为唯一的间接发现入口；未完成样本、字段、条款和备用方式审核前保持未启用。

## 目录与数据库结果

执行 `newsradar sources sync` 的结果：

```text
Synced 166 sources: 0 created, 52 updated, 114 unchanged
database_pair_statuses= {'duplicate': 19, 'needs_research': 19}
catalog_total= 166
enabled_sources= 54
```

结论：目录总数与已启用来源数均未改变；本次没有启用新来源、执行网络探测或真实抓取。

## 网页与审计结果

- 来源审计现在依据 YAML 的 `research.status` 判断占位，不再把带有 `universe-*-1/-2` 名称的记录自动判为占位。
- 详情页对“重复”“待研究”“占位”提供中文解释。
- 重复项详情说明其为历史目录项，不会参与探测或抓取。
- 待研究项说明其尚未完成样本、字段、条款和备用方式验证，不会自动启用。

## 自动化验证

- 研究审计与目录保护测试通过。
- 来源收口目录测试通过。
- 网页来源研究路由测试通过。
- 完整 pytest 与 Ruff 检查结果记录在本次提交的验证输出中。
