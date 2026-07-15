# Task 7：中文“全量盘点”网页报告

## 完成内容

- 新增 `SourceWaveQueryService`：只读取 `source_catalog_refresh` 操作，支持冻结成员的筛选、分页和无 N+1 的聚合统计。
- 新增 `/source-waves` 列表、创建、详情、取消、重试路由，并复用既有 loopback、同源及一次性 token 写入边界。
- 新增中文“全量盘点”导航、批次列表与成员详情页，展示五类互斥结果统计、通道、Provider、可用性、覆盖模式、状态、结果码及批次说明。
- 创建操作只加载本地已审核 YAML 并入队；网页请求不创建 HTTP 客户端，也不执行探测或网络访问。

## 验证

```text
uv run pytest tests/web/test_source_wave_queries.py tests/web/test_source_wave_pages.py tests/web/test_security.py -q
17 passed

uv run pytest -q --maxfail=1
通过（5 skipped）

uv run ruff check src/newsradar/web/source_wave_queries.py src/newsradar/web/app.py tests/web/test_source_wave_queries.py tests/web/test_source_wave_pages.py
All checks passed!
```

## 边界

- 未改动 Worker、真实网络、来源定义或摘要/推荐功能。
- 未读取或输出 `.env`、凭据、请求头或响应正文。
