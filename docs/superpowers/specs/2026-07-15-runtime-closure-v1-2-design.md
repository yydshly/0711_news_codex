# News Codex v1.2 运行闭环收口设计

## 1. 目标

v1.2 将现有来源、抓取、Worker、事件和 MiniMax 能力收口为一个适合个人日常使用的本机运行闭环，不重新设计来源架构，不增加摘要、推荐、推送或后台调度产品。

完成后，用户应能明确回答：

- 当前是否同时运行 Web 和 Worker；
- Worker 是在线空闲、正在执行、过期还是离线；
- MiniMax 是否由主运行时配置、模型是否受官方 API 支持、最近一次真实调用是否成功；
- YAML 当前目录与 PostgreSQL 历史记录是否一致；
- 哪些来源尚未探测、哪些 RSS 技术失败、哪些 HTML 只是被策略阻塞；
- 应从哪个中文网页入口查看以上结果。

## 2. 已确定边界

- 单用户、本机、回环地址运行，不引入 Docker。
- 采用现有 `newsradar serve` 作为唯一推荐日常入口。
- 不新增 Windows 服务、计划任务、后台 PID 管理器或网页进程控制按钮。
- Web 只入队和展示；正式抓取及事件任务仍由 Worker 消费。
- MiniMax 是辅助能力，失败不得阻塞规则流程。
- MiniMax Key 只存在于 Git 忽略的根目录 `.env`，不进入数据库、日志、报告、诊断包、网页或 Git。
- 来源 YAML 仍是当前目录真相；数据库保存历史、运行记录和归档状态。
- 历史来源不得因离开 YAML 而级联删除 RawItem、FetchRun 或事件证据。
- HTML 策略阻塞不得在健康波次中自动改为可抓取。
- Reddit 无正式权限时不得回退到 Cookie、登录态或网页抓取。
- 本阶段不实现定时抓取、中文日报、提醒、实体抽取、推荐或个性化。

## 3. 方案选择

采用方案 A：增强现有前台 `serve` 运行方式。

未采用方案：

- PID 文件后台管理：Windows 子进程树的可靠停止和异常恢复会扩大实现与安全范围。
- Windows 服务或计划任务：适用于后续无人值守阶段，当前个人开发期过重。
- 网页启停进程：Web 自身控制或终止兄弟进程容易产生残留、权限和自杀式停止问题。

## 4. 总体架构

```text
newsradar serve --host 127.0.0.1 --port 8766
  ├─ Web：只读查询、任务入队、取消/重试等受控本机操作
  └─ Worker：空闲心跳、任务租约、网络获取、事件处理、MiniMax 辅助

根目录 .env
  ├─ PostgreSQL 配置
  ├─ 来源凭据布尔状态
  └─ MiniMax Key、区域、模型

YAML 当前目录 ──sync/reconcile──> PostgreSQL 当前/归档来源
                               └─ 历史 RawItem、FetchRun、Probe、Event 保留
```

v1.2 分为两个连续批次：

1. 运行时收口：MiniMax、`serve`、Worker 心跳、系统网页、目录归档。
2. 来源健康波次：未探测与 RSS 失败来源的有界并发探测及中文报告。

两个批次属于同一里程碑，但必须分别提交和验收；第二批次不得反向修改第一批次的运行架构。

## 5. MiniMax 主运行时收口

### 5.1 官方接口口径

继续使用现有 OpenAI 兼容接口：

```text
POST {MINIMAX_BASE_URL}/v1/chat/completions
Authorization: Bearer <secret>
```

请求继续使用：

- `reasoning_split=true`；
- `temperature=1.0`；
- `max_completion_tokens`；
- 无工具、无文件、无环境访问；
- Pydantic 严格验证；
- JSON 或 Schema 错误最多一次修复；
- 总超时预算包含第一次请求与修复请求。

当前 MiniMax 官方 OpenAI 兼容模型列表包含 `MiniMax-M2.7` 和 `MiniMax-M2.7-highspeed`，未列出 `MiniMax-M3`。因此 v1.2 默认值改为：

```text
MINIMAX_BASE_URL=https://api.minimaxi.com
MINIMAX_DEEP_MODEL=MiniMax-M2.7
MINIMAX_FAST_MODEL=MiniMax-M2.7-highspeed
```

若未来官方账号的模型列表明确返回 M3，再通过配置切换，不提前硬编码未确认模型。

### 5.2 本地配置迁移

执行阶段允许从现有 `feature/raw-item-ingestion` 工作树的 Git 忽略 `.env` 中读取 MiniMax Key，并写入根目录 Git 忽略 `.env`。程序与命令不得输出 Key；迁移后只验证：

- `MINIMAX_API_KEY` 是否有值；
- 区域标签为“中国区”或“国际区”；
- 快速和深度模型名称；
- 官方模型检查与结构化调用结果。

不得删除或修改旧工作树的 `.env`。

### 5.3 健康检查命令

新增：

```text
newsradar minimax check
newsradar minimax check --live
```

默认模式只检查本地配置，不发起网络请求；`--live` 明确产生最多两类有界请求：

1. `GET /v1/models/{MINIMAX_FAST_MODEL}`，确认模型对当前 Key 可见；
2. 一次短小的 `infer_source_topics` 结构化调用，验证 JSON、Schema、token、延迟和使用记录链路。

终端只输出：配置状态、区域、模型、模型查询 HTTP 分类、结构化调用 outcome、token 和延迟。不得输出 Key、Authorization、完整提示词、模型正文或上游错误正文。

结构化调用通过现有使用记录 Sink 写入 `model_usage`；模型查询只输出脱敏结果，不写响应正文。

### 5.4 系统网页

`/system` 新增“MiniMax 运行状态”卡片，显示：

- 已配置/未配置；
- 中国区/国际区/自定义区域；
- 快速模型和深度模型；
- 历史 success/retry/fallback 数量；
- 最近一次调用时间、结果和安全错误码；
- 最近一次成功时间。

页面不得显示 Base URL 全文、API Key、token 值、请求正文、响应正文或错误原文。

## 6. Web 与 Worker 运行闭环

### 6.1 `serve` 参数

扩展现有命令：

```text
newsradar serve --host 127.0.0.1 --port 8766 --worker-id newsradar-local
```

`RuntimeSupervisor` 将参数分别传入 Web 与 Worker 子进程。任一子进程异常退出时，仍停止另一子进程并返回非零状态；Ctrl+C 仍同时停止两者。

不允许自动选择其他端口。端口被占用时必须失败并明确提示，避免用户打开错误实例。

### 6.2 Worker 空闲心跳

当前 Worker 只在租用任务时写心跳，导致一个真实存活但空闲的 Worker 在 `/system` 中显示 `stale`。v1.2 增加持久化空闲心跳：

- Worker 每次轮询前注册或更新自身；
- 无任务时状态为 `idle`，`current_operation_run_id=null`；
- 获取租约后状态为 `running` 并绑定任务；
- 完成、取消或失败后恢复 `idle`；
- 长任务继续按现有监控线程续租并写 `running` 心跳；
- 进程消失后不再写心跳，超过 5 分钟由查询层判定为 `stale`；
- 历史 Worker 行不删除。

新增 Repository 接口：

```python
def heartbeat_worker(self, worker_id: str, *, status: str = "idle") -> None
```

只允许 `idle` 或 `running`，空闲心跳不得覆盖仍绑定其他运行任务的 Worker。

### 6.3 系统健康投影

`SystemHealth` 增加：

- `online_worker_count`；
- `idle_worker_count`；
- `busy_worker_count`；
- `stale_worker_count`；
- `last_worker_heartbeat_at`。

中文显示规则：

- 5 分钟内、无当前任务：在线空闲；
- 5 分钟内、有当前任务：正在执行；
- 存在历史行但无新鲜心跳：心跳过期；
- 没有 Worker 行：尚未启动。

`/system` 增加“推荐运行方式”说明：

```text
日常启动：newsradar serve --host 127.0.0.1 --port 8766 --worker-id newsradar-local
日常停止：回到启动终端按 Ctrl+C
诊断模式：newsradar web / newsradar worker --once
```

网页不增加启动或停止按钮。

## 7. 来源目录归档与对账

### 7.1 数据结构

在 `source_definitions` 增加：

```text
catalog_state        current | archived，默认 current，非空
catalog_archived_at  可空时区时间
catalog_archive_reason 可空短文本
```

增加数据库约束，禁止未知 `catalog_state`。归档不改变来源 ID，不删除访问方式、版本、探测、抓取或 RawItem 历史。

### 7.2 同步语义

`SourceRepository.sync()` 对传入 YAML 来源执行：

- 新来源创建为 `current`；
- 已存在且归档的同 ID 来源恢复为 `current`；
- 恢复时清空归档时间与原因；
- 未出现在本次同步集合中的数据库来源保持不变，不隐式归档。

### 7.3 显式对账命令

新增：

```text
newsradar sources reconcile --root sources
newsradar sources reconcile --root sources --apply
```

默认只读输出：

- 当前 YAML 数量；
- 数据库 current 数量；
- 应归档 ID；
- 已归档但重新出现在 YAML 的 ID；
- 是否存在 queued/running Operation 引用。

`--apply` 才执行状态变更。若来源存在 queued/running Operation，拒绝归档并返回非零状态。归档原因为固定安全码 `absent_from_current_yaml`，不写任意用户文本。

首次执行应归档：

- `legacy-source`；
- `universe-youtube-1`。

### 7.4 查询与网页

- `/sources` 的当前 Target、探测、抓取和 RawItem 统计只使用 `catalog_state=current` 与 YAML 当前集合交集。
- 已归档且不在 YAML 的来源不再计为目录漂移。
- 能力总览新增“历史归档 Target”数量及链接。
- `/targets` 默认只显示 current；`?catalog_state=archived` 显示历史归档。
- `/targets/{id}` 对归档来源显示中文只读提示和归档原因，不提供抓取按钮。

## 8. 来源健康波次

### 8.1 选择规则

健康波次只从当前 YAML Target 中选择：

1. 没有任何 `source_probe_runs` 的 21 个未探测 Target；
2. 最新探测为 `failed` 且所选访问方式为 `rss` 或 `atom` 的目标。

不选择：

- 最新为 HTML 策略阻塞的目标；
- `catalog_only` 且无已批准内容方式的目标；
- 需要未配置凭据、审批或付费的目标；
- Reddit 权限阻塞目标；
- 已有最新 success 的目标。

选择结果必须在发起网络前输出 ID 和原因。

### 8.2 有界并发

`ProbeRunner` 增加最大并发参数，默认 `8`，范围 `1..16`。单个来源失败仍返回自己的 `ProbeResult`，不得取消其他来源。

新增命令：

```text
newsradar sources health-wave --root sources
newsradar sources health-wave --root sources --execute --concurrency 8
```

默认只生成选择计划；`--execute` 才发起探测并持久化结果。执行不修改 YAML、不自动启用来源、不调用 MiniMax。

### 8.3 中文报告

默认输出：

```text
reports/source-health-v1-2.md
```

报告包含：

- 执行时间与目录提交；
- 选择规则和来源清单；
- success/degraded/failed/blocked 分布；
- RSS/Atom 失败分类；
- 未探测剩余数量；
- HTML 策略阻塞数量，明确标记为策略而非技术故障；
- Reddit 等权限阻塞摘要；
- 每个失败来源的安全错误码、HTTP 状态、最近内容时间和下一步；
- 不包含响应正文、Cookie、代理地址、认证头或任何 Key。

## 9. 错误处理与安全

- MiniMax 配置缺失时健康检查返回明确 `not_configured`，不发网络请求。
- MiniMax 401/403/429/5xx、超时、业务错误和结构错误只保存现有安全错误码。
- Worker 心跳数据库失败时进程退出非零，不伪装为在线。
- `serve` 任一子进程退出时停止同组另一进程。
- 对账命令默认只读，`--apply` 不能删除数据。
- 健康波次默认只读计划，`--execute` 才发网络请求。
- 所有 HTTP 客户端继续继承本机系统代理与虚拟网卡路由；不记录代理值。
- 页面和报告只展示配置布尔状态，不展示敏感值。

## 10. 测试设计

### MiniMax

- 默认模型均在当前官方支持列表内；
- 配置检查不发网络请求；
- live 检查正确拼接中国区和国际区模型 URL；
- live 成功只输出脱敏摘要并保存 usage；
- 401、403、429、5xx 和超时输出安全错误码；
- Key、Authorization、提示词和响应正文不出现在输出、数据库或诊断包。

### Worker 与运行时

- 无任务的 `run_once` 创建或刷新 idle Worker；
- 租用任务切换为 running；
- 成功、失败和取消后切回 idle；
- 空闲心跳不覆盖仍绑定任务的 Worker；
- `serve` 正确传递 host、port、worker-id；
- 一个子进程异常退出会停止另一个；
- `/system` 正确区分在线空闲、正在执行、过期和未启动。

### 目录归档

- 迁移升级和降级通过；
- reconcile 默认不写数据库；
- `--apply` 只归档 YAML 缺失项；
- 有 queued/running Operation 时拒绝归档；
- 同 ID 重新同步会恢复 current；
- 历史 RawItem、FetchRun 和 Probe 仍可查询；
- `/targets` 默认排除 archived，可显式筛选。

### 健康波次

- 只选择未探测和最新 RSS/Atom failed 目标；
- 排除 HTML 策略阻塞和凭据/审批/付费目标；
- 最大并发不超过配置；
- 单源异常不影响其他来源；
- 默认计划模式不发网络、不写数据库；
- 中文报告不包含敏感信息。

### 总体验收

- 全量 pytest、Ruff 和 `git diff --check` 通过；
- 本地 PostgreSQL 迁移到 head；
- MiniMax 完成一次真实模型查询和一次结构化成功调用；
- `newsradar serve --host 127.0.0.1 --port 8766 --worker-id newsradar-local` 启动后，`/system` 显示 Worker 在线空闲；
- 两个历史来源归档，当前目录漂移为 0；
- 健康波次完成并生成中文报告；
- 浏览器验收 `/sources`、`/system`、`/targets?catalog_state=archived`、`/probes` 和 `/events`。

## 11. 完成标准

v1.2 完成必须同时满足：

1. 用户只需一个 `serve` 命令即可启动 Web 与 Worker；
2. 空闲 Worker 不再被误报为 stale；
3. MiniMax 主运行时已配置并有真实成功证据，失败仍可规则降级；
4. 当前目录与数据库 current 集合一致，历史来源保留为 archived；
5. 未探测和 RSS 失败来源完成一轮有界健康波次；
6. `/sources` 和 `/system` 用中文准确展示当前能力与缺口；
7. 没有新增摘要、推荐、推送、定时任务或高风险抓取能力。

