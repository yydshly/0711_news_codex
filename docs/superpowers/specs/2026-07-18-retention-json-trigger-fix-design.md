# 回收站 JSON 触发器修复设计

## 目标

让已归档日报可以安全移入回收站，同时继续禁止对日报正文、窗口、版本和关联关系的任意修改。

## 根因

PostgreSQL 触发器把 `generation_summary`（`json`）放进 `ROW(...) IS DISTINCT FROM ROW(...)` 比较。PostgreSQL 没有 `json = json` 运算符，因此即使只更新 `deleted_at` 与 `purge_after`，触发器也会抛出 `UndefinedFunction`。

## 方案

新增顺序迁移，重新定义归档日报保护函数：将 `generation_summary` 从行比较中移出，并以 `generation_summary::text IS DISTINCT FROM ...::text` 单独比较，保留 JSON 原始文本的不可变性。其他受保护列和已有的安全重挂父报告规则保持不变。

网页层把回收站操作中的完整性/编程类数据库异常转换为明确的中文“回收站操作失败”诊断；真正的连接失败和未迁移状态仍使用原有诊断。

## 数据与兼容性

迁移不改写任何日报、RawItem、事件或音频数据；只替换数据库函数定义。已有日报无需重新生成。修复后，用户可直接再次执行“移入回收站”。

## 验收

- PostgreSQL 上，对已归档日报仅写入回收站字段能够提交。
- 修改日报正文保护字段仍被触发器拒绝。
- SQLite 生命周期测试保持通过。
- 发生意外回收站数据库错误时，网页显示准确中文诊断而不是“查询数据库失败”。
