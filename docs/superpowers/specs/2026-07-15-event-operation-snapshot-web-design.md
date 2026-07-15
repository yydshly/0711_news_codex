# 最新 Operation 事件快照网页设计

日期：2026-07-15
状态：待实施
适用分支：`codex/event-quality-v2-1`

## 1. 背景与问题

当前事件质量报告按最新成功的 `event_pipeline` Operation 读取不可变的 `event_version_snapshots`，但网页事件首页、`/events` 和 `/emerging` 直接读取 `EventRecord.visibility=current`。

真实验收中出现了明确差异：

- Operation 781 的 72 小时快照包含 86 个事件，其中热点 0、新兴信号 78、仅审计 8；
- `/events?hours=72` 显示 100 个事件，其中热点 3、新兴信号 94、仅审计 3；
- 多出的 14 个事件由旧规则或旧 Operation 产生，但仍保留全局 `current` 状态。

因此，“网页当前事件”与“最新管线运行结果”并不是同一口径。用户无法从页面判断哪些内容属于最新一次能力验收，也无法可靠复现报告中的事件集合。

## 2. 目标

事件相关网页默认展示最新成功 Operation 的不可变快照，使网页与质量报告口径一致，同时保留全局 current 和 legacy 历史目录。

完成后用户应能明确看到：

- 当前展示对应哪个 Operation；
- Operation 的算法版本、窗口时长和窗口末端；
- 本次 Operation 包含多少事件、各层级多少；
- 列表和详情是否属于同一个事件版本；
- 如何切换到全局 current 目录或 legacy 历史。

## 3. 非目标

本阶段不做以下事项：

- 不自动把旧事件更新为 `legacy`；
- 不删除或重写任何 `EventRecord`、`EventVersionRecord` 或 Operation；
- 不改变聚类、评分、证据、MiniMax 或来源启用规则；
- 不增加摘要、推荐、推送和调度功能；
- 不把聚合源升级为独立事实证据。

## 4. 方案比较

### 方案 A：最新 Operation 快照作为默认视图（采用）

网页读取最新成功 Operation 中明确记录的事件 ID 和版本号。全局 current 目录作为次级入口保留。

优点：

- 不修改历史数据，风险最低；
- 与质量报告天然一致；
- 列表可复现，便于审计；
- 不受旧事件 `current` 状态影响。

代价：

- 查询层需要支持指定事件版本；
- 详情 URL 需要携带 Operation 或版本上下文。

### 方案 B：每次管线完成后自动将缺席事件转为 legacy（不采用）

优点是全局 current 目录本身保持整洁。风险是不同窗口、不同算法版本和并发 Operation 可能错误退役仍有效事件，且需要新的写事务和恢复机制。

### 方案 C：网页同时混合显示最新快照与全局 current（不采用）

实现较快，但用户仍需理解两套数字，无法真正消除当前歧义。

## 5. 页面信息架构

### 5.1 默认视图

以下页面默认使用最新 Operation 快照：

- `/`：事件情报首页；
- `/events`：最新运行的全部事件；
- `/emerging`：最新运行中的新兴线索；
- `/events/{event_id}?operation={operation_id}&version={version_number}`：指定 Operation 的精确事件版本。

页面顶部显示统一快照说明：

- `最新运行快照 · Operation #781`；
- `72 小时窗口`；
- `算法：relevance-v2 / newsworthiness-v2 / cluster-v2 / score-v2`；
- Operation 完成时间；
- 当前快照事件总数与热点/信号/仅审计数量。

### 5.2 历史入口

保留两个显式入口：

- `/events?scope=current_catalog`：数据库全局 current 目录；
- `/events?visibility=legacy&scope=catalog`：legacy 历史目录。

页面必须说明“全局 current 目录可能包含不同 Operation 产生的事件，不等同于最新运行快照”。

### 5.3 筛选语义

快照视图支持现有状态、类别、层级和时间范围筛选。

- 状态、类别和层级读取指定 `EventVersionRecord.payload` 的快照字段；
- 时间筛选以 Operation 的 `window_end` 为上界，而不是浏览器打开页面的当前时间；
- `最近 24/72/168 小时` 都相对该 Operation 的窗口末端计算；
- 默认不再用 `EventRecord.current_version_number` 决定版本。

这样同一 URL 在 Operation 数据不变时能够返回同一事件集合。

## 6. 查询层设计

### 6.1 新增只读对象

新增内部只读结构：

- `OperationSnapshotRef`
  - `operation_id`
  - `window_hours`
  - `window_end`
  - `finished_at`
  - `algorithm_versions`
  - `event_versions: tuple[(event_id, version_number), ...]`
- `OperationEventPage`
  - `snapshot`
  - `events`
  - `filters`
  - `tier_counts`

### 6.2 选择最新快照

查询服务只接受满足全部条件的 Operation：

1. `operation_type=event_pipeline`；
2. `status=succeeded`；
3. `requested_scope.algorithm_versions` 与当前 `EVENT_ALGORITHM_VERSIONS` 完全一致；
4. `requested_scope.window_end` 是合法且不晚于当前时间的 ISO 时间；
5. `result_summary.event_version_snapshots` 是有界、无重复的正整数 ID/版本号列表；
6. 每个引用的事件版本和评分快照都存在。

按 Operation ID 倒序选择第一条完整快照。失败、运行中、旧算法、字段损坏或版本缺失的 Operation 不得成为默认网页快照。

### 6.3 精确版本查询

通过一次有界查询加载：

- `EventRecord`：只用于稳定事件 ID 和 canonical key；
- 指定版本的 `EventVersionRecord`；
- 同版本的 `EventScoreRecord`。

状态、类别、发生时间、展示层级和排名从版本 payload/score 快照投影，不使用事件表当前指针覆盖历史事实。

事件数量上限沿用报告层的安全上限；超出、重复、布尔值伪装整数或缺失版本均视为快照无效，不能部分显示成完整结果。

## 7. 详情页一致性

快照列表中的详情链接必须携带 `operation` 和 `version`。

详情查询验证：

- Operation 确实包含该 `(event_id, version_number)`；
- 指定版本存在；
- 证据成员关系按该版本的 `added_version_number` 和 `removed_version_number` 计算；
- 评分、中文增强、证据角色和限制均来自同一版本。

直接访问不带 Operation 参数的 `/events/{event_id}` 继续表示“全局 current 详情”，页面上标记其不是固定 Operation 快照。

## 8. 无可用快照与异常处理

如果没有合法的最新成功快照：

- 页面显示中文阻塞说明；
- 提供“查看运行任务”和“查看全局 current 目录”入口；
- 不静默回退到全局 current，避免用户误以为那是最新运行结果；
- 不在网页输出数据库错误、连接串、请求参数或原始异常。

如果某条更晚 Operation 损坏，查询层跳过它并尝试上一条满足当前算法版本的成功完整快照，同时在页面显示“已使用最近完整快照”的安全提示。

## 9. 并发、可靠性与性能

- 网页只读，不获取事件租约，不修改 Operation；
- Operation 只有在 `succeeded` 后才可被选中，避免读取发布中间状态；
- 使用 Operation 中的精确版本号，后续 Worker 发布新版本不会改变已打开快照的含义；
- 事件和评分采用集合查询，禁止逐事件 N+1 查询；
- 页面最大返回数量继续受现有上限控制；
- 旧 Operation 和历史事件不删除，任何时候可以审计。

## 10. 安全边界

Operation 的 JSON 字段按不可信数据库数据处理：

- 只允许已知键、已知枚举、正整数和有界字符串；
- 算法版本必须精确匹配程序常量；
- 页面不渲染 Operation 原始错误、任意 details、URL 查询参数或凭据；
- 详情外链继续经过现有安全 URL 投影；
- MiniMax 不参与快照选择和页面口径判断。

## 11. 测试与验收

### 11.1 查询层测试

- 选择最新成功且算法版本匹配的完整 Operation；
- 跳过 failed、running、旧算法和损坏快照；
- 精确读取指定事件版本，不受 `current_version_number` 后续变化影响；
- 拒绝重复 ID、布尔值 ID、超限列表和缺失版本；
- 时间筛选相对 `window_end`，不依赖系统当前时间；
- 一次集合查询返回事件与评分，不出现 N+1；
- 全局 current 和 legacy 查询保持兼容。

### 11.2 路由与模板测试

- `/events` 默认显示 Operation 编号、窗口和算法版本；
- 快照详情链接包含 Operation 与版本参数；
- `scope=current_catalog` 明确显示全局目录提示；
- 无合法快照时显示阻塞说明而非静默回退；
- `/emerging` 和事件首页使用同一 Operation；
- 原始错误、密钥、连接串和不受信 JSON 不出现在 HTML。

### 11.3 真实浏览器验收

以最新成功 Operation 为基准：

- 网页事件总数与 `event-quality-v2-1.md` 一致；
- 热点、信号、仅审计数量一致；
- 随机打开至少 5 个详情，事件版本、证据数和评分与 Operation 快照一致；
- 切换到全局 current 目录后，页面明确显示不同口径；
- Worker 并发发布下一次 Operation 时，已打开的旧快照链接仍可复现。

## 12. 完成条件

- 最新 Operation 快照成为所有事件主页面的默认口径；
- 网页与质量报告不再出现 86 对 100 的无解释差异；
- 列表和详情使用同一事件版本；
- 全局 current 与 legacy 历史仍可访问；
- 没有任何事件数据被自动删除或退役；
- 全量测试、Ruff、密钥扫描和真实浏览器验收通过。
