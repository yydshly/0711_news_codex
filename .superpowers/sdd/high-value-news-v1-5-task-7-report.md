# Task 7 完成报告：中文热点页面与安全入队

## 交付内容

- 首页在同一份完整事件快照中分开呈现“最近 24 小时已确认热点”“早期信号”和“7 天趋势”。
- 事件详情补充热度趋势、来源角色汇总和缺失确认条件；既有证据时间线、六项评分、原始链接与 MiniMax 降级标记保留。
- `POST /events/update` 只加载本地审核过的 Profile/YAML、同步定义并冻结波次计划，再入队 `high_value_news_wave`；页面请求不创建 HTTP 客户端、不抓取外部网站、不调用 MiniMax。
- 写入入口复用 loopback Host、same-origin/受控 opaque-origin 和一次性 action token 校验；重复 token 返回 400。
- CLI 新增：
  - `newsradar waves enqueue --profile ...`
  - `newsradar waves status <operation-id>`
  - `newsradar waves report <operation-id> --output ...`
- CLI 状态/报告只读取已冻结任务；报告对可能的凭据文本执行脱敏。

## TDD 证据

先新增 `tests/web/test_high_value_wave_pages.py`，确认首页分区、详情解释和 `/events/update` 在实现前失败；随后实现最小功能转绿。另新增 CLI 入队、状态、报告不联网/不调用模型的回归测试。

## 最终验证

```text
uv run pytest tests/web -q
167 passed

uv run ruff check src/newsradar/web src/newsradar/cli.py tests/web tests/test_cli.py
All checks passed

git diff --check
通过
```

Starlette TestClient 的第三方弃用警告仍存在，但没有测试失败或新的应用警告。
