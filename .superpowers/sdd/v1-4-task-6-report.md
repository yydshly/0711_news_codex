# v1.4 Task 6：CLI 计划、入队、状态与中文报告

## 实现

- 新增 `sources refresh-plan`：只加载严格校验后的 YAML，输出内容、能力、目录三通道及目录摘要；不打开数据库、不创建任务、不进行网络访问。
- 新增 `sources refresh-enqueue`：同步 Provider/Source YAML 后创建冻结的 `source_catalog_refresh` 操作；CLI 本身不运行探测。
- 新增 `sources refresh-status` 与 `sources refresh-report`：仅读取指定冻结批次；未知或非目录刷新操作以明确的中文错误退出。
- 新增 `catalog_refresh_reporting.py`：固定顺序中文 Markdown 报告，仅汇总通道、状态、结果码及轮次数量；不渲染自由文本结论、密钥、鉴权头、会话信息、环境变量配置或响应头。

## 验证

- `uv run pytest tests/test_cli.py -q`：通过。
- `uv run pytest -q --maxfail=1`：通过（既有 Starlette/Alembic 弃用警告）。
- 目标 Ruff 检查：通过。
- `uv run newsradar sources refresh-plan --root sources --provider-root providers`：纯计划成功，内容 106、能力 20、目录 61。

## 说明

既有 `task-6-report.md` 是早期 Event pipeline 的历史报告，故未覆盖它。

## 复审修复

- `refresh-status` 现在额外输出实际出现的成员状态分布，固定状态顺序为
  pending、running、succeeded、blocked、degraded、failed、cancelled。
- `summarize_catalog_members` 的返回契约收紧为仅包含 `lanes`、`states` 与
  `result_codes` 三类聚合；内容三轮证据仍由报告渲染时直接从冻结成员计算。
- 已新增 CLI 回归断言并重新通过完整测试与 Ruff 检查。
