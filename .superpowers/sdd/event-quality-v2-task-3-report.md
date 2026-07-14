# Event Intelligence v2 Task 3 实现与复审修复报告

## 状态

- 状态：完成
- 分支：`codex/event-quality-closure`
- 初始实现提交：`ae9d0b34804bf7c38f6a083ab47877b6f36c9315`
- 范围：Event Intelligence v2 Task 3、独立复审 A–G 以及最终四项小范围闭环
- 未修改：来源 YAML、Web 页面、MiniMax 适配器

## 最终实现

### A. Operation 固定快照

- Pipeline 严格选择 `cutoff <= event_time <= window_end`，未来 10 天数据不会被纳入。
- `window_end` 从持久化 Operation 读取；aware ISO 转 UTC，naive ISO 按 UTC 解释。
- 缺失或非法值稳定回退到 `OperationRunRecord.created_at`，并记录 `operation_window_end_fallback` checkpoint；Operation 不存在时明确失败。
- `enqueue_event_pipeline()` 将精确入队时刻写入 scope；整点 bucket 只用于幂等键，避免本小时新数据被误判为未来。

### B. 30 天 novelty

- Candidate metadata 持久化 `_core_identity=核心对象|动作`；没有核心对象时保存 `null`，避免无关事件共享伪身份。
- 查询当前 Event 与 `cluster-v2` candidate，在 `[window_end-30d, window_end]` 内按核心身份聚合历史独立证据根。
- novelty 保持 100/50/0：无先前事件、新独立根、纯重复。
- URL、repository、paper 等不可变身份的 candidate key 不依赖日期或 anchor；普通对象事件仍有日期边界，避免无限合并。

### C. 确定性实体

- 支持 GPT-5、Claude 5、Gemini 2.5、Qwen3、DeepSeek-R1 等版本模型。
- 支持长引号论文标题以及 `owner/repo` 项目实体。
- 真实 GPT-5 跨 URL 标题可通过共享模型对象与动作聚类。

### D. Reclustering 真实重评分

- 每个 retained/split candidate 都从其成员的 `relevance-v2`、Source authority、RawItem engagement、证据、Operation 固定时间和历史证据根独立构建 score-v2 输入。
- 先为全部 candidates 完成输入构建，再发布任何版本；任一必需输入缺失时返回 `event_quality_input_unavailable`。
- 失败 transaction 回滚且释放 lease；旧 Event 当前版本号和 EventVersion 数量保持不变。

### E. 不可变 Candidate 快照发布

- 新增 `publish_snapshot()` / `assemble_snapshot()`，评分、证据和成员均来自同一不可变 `CandidateCluster`。
- 即使模型调用期间数据库 candidate membership 被并发替换，最终发布仍使用评分时快照。
- 模型网络调用期间没有打开的 DB session/transaction 或 event lease。

### F. 输入安全

- engagement 仅接受显式白名单字段，不再接受任意 `*_count`（例如 `error_count`）。
- relevance 与 authority 对每个成员均为必需映射；缺失、非数值或非有限值明确失败，不能静默记 0。

### G. 48 小时组件性能

- Union-find 根维护 component 最小/最大发布时间，合并检查从成员笛卡尔扫描改为 O(1) 时间跨度判断。
- 100/200 条密集同主题性能回归对 `_find` 调用数设置二次上界。
- 旧实现运行超过 60 秒仍未完成；优化后两个规模用例合计约 1.6 秒。

### H. Operation v2 版本身份

- 新增不可变共享版本映射，Pipeline 与 Operation command 同时消费 `relevance-v2/entities-v2/cluster-v2/score-v2`。
- Operation scope 与幂等键均包含完整四项版本；精确 `window_end` 只写 scope，小时 bucket 只参与幂等身份。
- 同一小时已有旧 v1 Operation 时，v2 请求生成不同幂等键，不会复用旧身份。

### I. Reclustering 原事件 novelty

- runtime 构造每个 split candidate 的 score 输入时显式传入原 `EventRecord`。
- 原事件当前版本的独立 evidence roots 作为 prior roots；原成员拆分属于纯重复，两个 candidate 均为 novelty 0 / `novelty:pure_repeat`。
- 常规 Pipeline 的 30 天核心身份查询保持不变；真正出现新独立根时仍由既有 quality 规则得到 novelty 50。

### J. 论文与开源动作归一

- `publish/publishes/published` 统一映射到 launch/release 动作。
- `open source/open sources/open sourced` 及连字符变体统一映射；单独、非相邻的 `open` 或 `source` 不构成动作。
- 同 paper 或同 `owner/repo` 的跨 URL 报道在 48 小时内可以稳定匹配。

### K. Engagement 截断顺序

- quality 暴露共享白名单过滤函数，Pipeline 与 score 构建共同使用。
- 先过滤白名单及非法数值，再应用最多 20 字段限制，垃圾字段不能挤掉 `views`、`score` 等有效互动。

## RED 证据

- Operation：未来数据被选中；缺失 Operation 回退墙钟。
- Novelty：相邻日期同对象/动作未识别为历史事件。
- 实体：版本模型、长论文标题、repository 未稳定抽取。
- Reclustering：split candidates 复用旧事件的同一分数（80/80），缺 relevance-v2 仍错误成功。
- Snapshot：并发替换 persisted candidate members 后发布了错误成员。
- Safety：`error_count` 被当作 engagement，缺失 relevance/authority 静默计 0。
- Performance：100/200 密集组件旧实现超过 60 秒未结束。
- 最终复审 RED：Operation 仍写 v1 三版本；两个 recluster split novelty 错为 100；publish/open-source 动作未识别；20 个垃圾字段先占满 engagement 上限。

## GREEN 证据

- 事件聚焦：
  - `.venv\\Scripts\\python.exe -m pytest -q tests/events/test_quality.py tests/events/test_entities.py tests/events/test_clustering.py tests/events/test_pipeline.py tests/events/test_publishing.py tests/events/test_runtime.py`
  - 结果：105 passed。
- 最后代码清理后的相关复验：
  - `.venv\\Scripts\\python.exe -m pytest -q tests/events/test_quality.py tests/events/test_pipeline.py`
  - 结果：35 passed。
- 全量回归：
  - `.venv\\Scripts\\python.exe -m pytest -q`
  - 最终结果：891 collected，888 passed，3 skipped；仅既有 Starlette/Alembic 弃用警告。
- 静态检查：Ruff `All checks passed!`。
- 差异检查：`git diff --check` 通过；仅 Windows LF/CRLF 提示。
- 最终四项 RED/GREEN 聚焦：首轮 9 failures（另 2 个裸词负例按预期通过），最小修复后 12 passed。
- 最终四项相关回归：127 passed；仅既有 Starlette 弃用警告。
- 最终串行验证门（Ruff、diff-check、全量 pytest）总耗时约 70.1 秒，exit 0。

## 边界说明

- Source authority 的生产契约为 0–5；旧测试 fixture 中的 90 会安全 clamp 到 5，再映射为 100。
- Operation scope 缺失 `window_end` 只允许回退到该 Operation 自身的稳定 `created_at`，绝不回退墙钟。
- 没有可靠核心对象的 candidate 不参与跨事件 novelty 身份匹配。
- 首次并发发布触发 Event 唯一键竞争时的 loser retry 属于 Task 4 可靠性范围，本轮按复审决定不扩展。
