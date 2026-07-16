# 手动中文日报 MVP：最终审查修复报告

基线：`f66306f6d3e971767791c6ce9bcbe4074f2b93a0`

## 完成范围

- 普通日报以 `report_date + window_hours + source_operation_id` 作为永久身份；归档后重复生成返回原归档记录。
- 显式修订以 `supersedes_report_id` 作为永久身份；直接子版本无论 draft/archived 均被复用，修订链不能从旧父版本分叉。
- 保留原 revision 唯一约束、PostgreSQL advisory lock、三次有限重试及冲突后的 session rollback/继续使用行为。
- 迁移增加普通身份部分唯一索引、直接子版本唯一索引，以及 `status` / `archived_at` 一致性 check。
- SQLite 增加 5 个原生 trigger，拒绝归档 report/item 的 UPDATE、DELETE、INSERT 及把 item 移入归档 report。
- PostgreSQL 增加 report/item guard function 与 trigger；item guard 按 report id 排序锁定父记录后检查归档状态，避免与并发 archive 的 TOCTOU。
- downgrade 先清理 trigger/function/index，再删除日报表。
- 未处理 N+1 minor，未触碰 `reports/`、`.env`、Event/RawItem、抓取或模型代码，未连接/停止 8766。

## TDD 证据

1. Repository/Web RED：新增 5 个回归场景后，出现 5 个预期失败：普通归档后重复生成、归档子版重复修订、web 旧父修订、两个新唯一约束的并发恢复。
2. Repository/Web GREEN：`52 passed`。
3. Migration RED：新增唯一索引、trigger、归档直接 SQL 写保护、状态时间一致性测试后，`12 failed`。
4. Migration GREEN：`12 passed`。

## 验证结果

- `tests/daily_reports tests/web/test_daily_report_pages.py tests/test_migrations.py`：`120 passed`。
- Ruff（所有变更 Python 文件）：`All checks passed!`。
- 独立临时 PostgreSQL UTF8 cluster：完整 `upgrade head`、归档后 report/item UPDATE/DELETE/INSERT 写保护、状态 check、`downgrade 20260716_0022` 及 function 清理均通过；临时实例已停止并删除。
- `git diff --check`：通过。

## 已知风险

- PostgreSQL guard 的真实方言 SQL已在本机临时实例验证，但当前 pytest 自动化仅直接运行 SQLite migration；PostgreSQL 真实验证仍属于手动验收证据。
- ORM `Base.metadata.create_all()` 只用于测试辅助，数据库级 trigger/function 由 Alembic 迁移安装；本次按 brief 文件范围未扩展 ORM 模型元数据或测试框架。

## 同 revision 旧 0023 兼容修复

- 项目数据库曾在相同 `20260716_0023` revision 下创建日报表，但没有后续补入的 `uq_daily_report_identity` / `uq_daily_report_supersedes` 索引；严格 `drop_index` 会使 downgrade 在缺失索引处失败并回滚。
- TDD RED：升级当前 head 后显式删除两个索引，再 downgrade 到 `20260716_0022`，原实现稳定报 `no such index: uq_daily_report_supersedes`。
- 最小 GREEN：仅为这两个后加索引的 Alembic `drop_index` 设置 `if_exists=True`；SQLite 回归通过，核心事件表保留。
- 未连接或修改项目真实数据库；真实数据库同步由根任务在此提交后另行执行。
