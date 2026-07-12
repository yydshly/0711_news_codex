# Task 6 实施报告：Provider 与 Target 目录

## 状态

已实现 Provider/Target 列表、筛选、详情下钻、脱敏展示、外链保护、表格键盘滚动与移动端筛选布局。

## 接口裁决

简报要求 Provider 列表展示认证与能力、Target 列表展示角色，但原有 `ProviderRow` / `TargetRow` 不含这些字段。经主任务确认，采用向后兼容的尾部默认字段扩展：

- `ProviderRow` 新增 `auth_mode: str = ""`、`auth_label: str = "未记录"`、`capabilities: tuple[str, ...] = ()`。
- `TargetRow` 新增 `roles: tuple[str, ...] = ()`、`role_labels: tuple[str, ...] = ()`。
- 不改变既有字段顺序、名称或语义；旧构造调用继续有效。
- `DashboardQueryService` 直接从已加载的 Provider/Source 记录填充字段，不增加逐条详情查询或 N+1。

## RED

先新增路由和查询回归测试，再运行：

```text
uv run pytest tests/web/test_routes.py tests/web/test_queries.py -v
```

结果：`11 failed, 16 passed`。预期失败包括：

- `/providers`、`/providers/{provider_id}`、`/targets`、`/targets/{source_id}` 尚不存在，返回 404。
- `ProviderRow` 不接受 `auth_mode` 等新尾部字段。
- 查询结果没有 Provider 认证/能力与 Target 角色元数据。

失败均由待实现功能缺失导致。

## GREEN

完成最小实现后运行同一聚焦命令：

```text
27 passed, 1 warning in 1.54s
```

覆盖行为：

- FastAPI `Literal` 查询参数验证当前枚举字符串；`q` 去首尾空白并截断至 100 字符。
- 活跃筛选条件回显到真实 GET 表单。
- Provider/Target 列表完整展示批准字段，并链接详情页。
- 详情页展示登记、能力探测、内容探测、访问方式、风险、审核证据与解锁信息，明确区分不同口径。
- 未知 Provider/Target 返回中文 404。
- 环境变量仅展示名称；模板不接收 access method headers，也不展示 Authorization、Cookie、数据库密码或密钥值。
- 所有外链带 `target="_blank" rel="noopener noreferrer"`。
- 表格位于带标签、`tabindex="0"` 的横向滚动区域；760px 以下筛选纵向堆叠。

## 验证

- 聚焦：`uv run pytest tests/web/test_routes.py tests/web/test_queries.py -v` → 27 passed。
- Ruff：`uv run ruff check src/newsradar/web tests/web` → All checks passed。
- 全量（仅执行一次）：`uv run pytest -v` → 116 passed，1 个既存 Starlette/httpx 弃用警告。
- `git diff --check` → 无空白错误。

## 自审

- 公共 ViewModel 扩展保持向后兼容，默认值位于末尾。
- 列表查询复用已有批量加载路径，无 N+1。
- 四个新模板不引用 headers、Authorization、Cookie、数据库 URL 或密码字段。
- 没有 MiniMax 调用、外部写操作或远端探测。
- `reports/live-source-universe.md` 与 `reports/source-coverage.md` 的既有改动未修改、未暂存。

## 关注点

- 测试环境仍报告 Starlette `TestClient` 使用 `httpx` 的弃用警告；与本任务无关，不影响通过结果。
