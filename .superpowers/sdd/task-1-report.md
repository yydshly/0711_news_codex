# Task 1 实施报告

## 交付内容

- 新增 `newsradar.sources.catalog_refresh`，提供三组枚举、冻结成员快照、可复现计划和纯目录校验结果。
- `build_catalog_refresh_plan` 只使用传入的来源、Provider、最新结果和已配置凭据；不读取环境、不访问网络或数据库。
- 计划成员按 `source_id` 排序，使用规范 JSON 与 SHA-256 生成稳定摘要，并统计各 lane 成员数。
- 已覆盖 content、capability、catalog 路由，缺失凭据、归档排除、旧结果 access kind 不一致、输入重排稳定性，以及目录字段完整性与无 HTTP 调用。

## TDD 记录

1. 先新增 `tests/test_catalog_refresh.py`，再运行定向测试。
2. RED：因 `newsradar.sources.catalog_refresh` 尚不存在，测试收集阶段以 `ModuleNotFoundError` 失败。
3. 实现最小纯函数模块后，定向测试通过；随后修正 Ruff 报告的导入与行长问题。

## 验证

- `python -m pytest tests/test_catalog_refresh.py -q`：6 passed。
- `python -m ruff check .`：All checks passed。
- `python -m pytest -q`：通过（保留既有 2 类弃用警告：Starlette TestClient 和 Alembic `path_separator`）。

## 审查修正

- `CatalogRefreshPlan` 现在以 `catalog_digest` 提供计划摘要，并将 `lane_counts` 暴露为只读 mapping；保留 `digest` 属性兼容早期调用方。
- `CatalogValidationResult` 现在以 `missing` 提供缺失字段；保留 `missing_fields` 属性兼容早期调用方。
- 增加 ready 来源在全部 `auth_envs` 已提供时进入 `content` lane 的正向测试。
- 审查修正后重新执行定向测试（7 passed）、完整 pytest 与完整 Ruff，均通过。

## 范围确认

未修改数据库、CLI、Worker、Web、YAML 或其他业务文件；实现没有 HTTP、Cookie、登录态、验证码、代理或 HTML 自动回退行为。
