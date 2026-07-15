# Task 8 验收报告

## 范围与环境

- 基线提交：`84bd433`；验收提交：`851b949`、`922abbd`、`2bced73`、`c0af90d`、`46bc727`。
- 追加验收修复：`6c354e9`、`943df4d`、`6e413a3`。
- 恢复终态修复：`0742d6c`。
- 根目录 `.env` 仅加载到子进程环境，未输出、记录或提交任何值。
- PostgreSQL 迁移已执行并确认：`20260715_0017 (head)`。
- 临时 Web 服务只使用 `127.0.0.1:8767`；根工作树的 8766 服务未触碰。

## 真实批次证据

- `providers sync`：67；`sources sync`：187；`sources refresh-plan`：内容 106、能力 20、目录 61，合计 187，且规划命令不访问网络。
- 操作 `827` 由 `/source-waves` 入队（约 362 ms）并由独立 Worker 消费；中途 `77/187`，终态 `partial`、`187/187`，无 `running` 成员。
- 终态成员：succeeded 102、blocked 19、degraded 64、failed 2；五类状态合计 187。内容三轮成功为 102/106。
- 操作 `828` 在 `running` 时执行网页取消并终态 `cancelled`。PostgreSQL 验收测试验证 Web 入队、Worker 终态、187 冻结成员与三通道互斥；另有 catalog-handler 测试验证取消边界后不再探测、过期租约仅处理未完成成员且成功成员 probe 数不增长、以及并发终态只计数一次。

## 结果与限制

- AP/Reuters/Bloomberg/FT/WSJ 内容成员具有新的三轮内容结论；DeepMind/Hugging Face 为 `incomplete_fields`，Anthropic Bluesky 为 `no_content`，SEC EDGAR 为 `requires_approval` 能力结论，No Priors 维持目录/能力边界。
- GDELT 实测为上游 `rate_limited`，如实保存而非伪造 `timeout`；Microsoft Research 发生单成员 `internal_error`，未阻断批次。
- 浏览器控制运行时返回“无可用浏览器”。因此未取得浏览器控制台证据；已通过临时服务 HTTP 检查 `/source-waves`、详情、筛选参数及取消入口。

## 缺陷修复

- 验收发现成员完成时未更新 `OperationRunRecord.progress_current`，实际页面会持续显示 `0/187`。修复为成员首次离开 `pending/running` 时仅加一次，并把 `completed_count` 写入最终 `result_summary`；回归与 PostgreSQL 端到端测试均已通过。

## 门禁

- 定向 PostgreSQL 验收：通过。
- 定向 PostgreSQL/repository：11 passed；完整 `pytest -q --maxfail=1` 通过；ruff、provider/source validate、`git diff --check` 通过。`main..HEAD` 敏感扫描仅命中一个既有测试形状，本任务新增提交无敏感值。
- `0742d6c` 后最终复跑：PostgreSQL acceptance 4 passed（未跳过），完整 pytest、ruff、provider/source validate、diff check 均通过；敏感扫描结果仍为一个既有测试形状。
