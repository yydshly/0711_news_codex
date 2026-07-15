# Task 8 验收报告

## 范围与环境

- 基线提交：`84bd433`；实际代码修复后另见本任务提交。
- 根目录 `.env` 仅加载到子进程环境，未输出、记录或提交任何值。
- PostgreSQL 迁移已执行并确认：`20260715_0017 (head)`。
- 临时 Web 服务只使用 `127.0.0.1:8767`；根工作树的 8766 服务未触碰。

## 真实批次证据

- `providers sync`：67；`sources sync`：187；`sources refresh-plan`：内容 106、能力 20、目录 61，合计 187，且规划命令不访问网络。
- 操作 `827` 由 `/source-waves` 入队（约 362 ms）并由独立 Worker 消费；中途 `77/187`，终态 `partial`、`187/187`，无 `running` 成员。
- 终态成员：succeeded 102、blocked 19、degraded 64、failed 2；五类状态合计 187。内容三轮成功为 102/106。
- 操作 `828` 在 `running` 时执行网页取消并终态 `cancelled`。PostgreSQL 验收测试验证 Web 入队、Worker 终态、187 冻结成员与三通道互斥；租约恢复与成功成员不重复探测由现有运行时/仓储回归测试覆盖。

## 结果与限制

- AP/Reuters/Bloomberg/FT/WSJ 内容成员具有新的三轮内容结论；DeepMind/Hugging Face 为 `incomplete_fields`，Anthropic Bluesky 为 `no_content`，SEC EDGAR 为 `requires_approval` 能力结论，No Priors 维持目录/能力边界。
- GDELT 实测为上游 `rate_limited`，如实保存而非伪造 `timeout`；Microsoft Research 发生单成员 `internal_error`，未阻断批次。
- 浏览器控制运行时返回“无可用浏览器”。因此未取得浏览器控制台证据；已通过临时服务 HTTP 检查 `/source-waves`、详情、筛选参数及取消入口。

## 缺陷修复

- 验收发现成员完成时未更新 `OperationRunRecord.progress_current`，实际页面会持续显示 `0/187`。修复为成员首次离开 `pending/running` 时仅加一次，并把 `completed_count` 写入最终 `result_summary`；回归与 PostgreSQL 端到端测试均已通过。

## 门禁

- 定向 PostgreSQL 验收：通过。
- 其余完整 pytest、ruff、validate、敏感模式扫描与 `git diff --check` 见最终门禁记录。
