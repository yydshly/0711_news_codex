# 主分支运行时归属迁移实施计划

> **面向代理执行者：** 本计划涉及本地 PostgreSQL 持久化数据。按任务顺序执行；任何前置检查失败时停止，不删除旧工作树、旧数据或 `.env`。

**目标：** 将 News Codex 本地 PostgreSQL 数据目录复制并切换到 `main/.local/postgres`，使主分支可独立运行。

**架构：** 采用“停旧服务、复制验证、启新服务、可读校验、运行时验收”的单机切换。旧工作树的数据目录只读保留，作为无需重建的回滚源；主分支的 `.env` 继续使用被 Git 忽略的本机配置。

**技术栈：** Python 3.12、PostgreSQL、本机 PowerShell、Alembic、Typer、FastAPI、Uvicorn。

## 全局约束

- 新增说明、计划和验收文档使用中文。
- 不记录或输出 API Key、数据库密码、Cookie 或完整数据库连接串。
- 不删除 `feature/local-postgresql-runtime` 或 `feature/raw-item-ingestion` 工作树，以及其中 `.env`、`.local/postgres` 或未提交报告。
- 不执行网络抓取、MiniMax 调用或事件发布；验收仅允许读取现有数据及运行确定性本机任务。
- 数据目录复制前，端口 `55432` 必须不再监听；复制后只有 `main` 启动该端口。

---

### 任务 1：建立迁移前基线与回滚证据

**文件：**
- 创建：`main/.local/runtime/main-runtime-migration-baseline.json`（被 Git 忽略）
- 创建：`main/.local/runtime/main-runtime-source-manifest.txt`（被 Git 忽略）
- 读取：`.worktrees/raw-item-ingestion/.local/postgres`

**产物：** 一份不含机密的基线，记录来源目录的文件数、总字节数、数据库迁移版本，以及来源/任务/原始条目/事件的只读计数。稳定 SHA-256 清单在服务停止后生成，避免把运行期 PID 文件纳入比较。

- [x] **步骤 1：确认切换前条件**

运行：

```powershell
Test-Path .local/postgres                 # 预期 False
Test-Path .worktrees/raw-item-ingestion/.local/postgres # 预期 True
uv run alembic current                    # 预期 20260712_0008 (head)
```

- [x] **步骤 2：生成不含机密的目录和数据基线**

运行：

```powershell
$source = '.worktrees/raw-item-ingestion/.local/postgres'
Get-ChildItem -LiteralPath $source -Recurse -Force -File |
  Where-Object { $_.FullName -notlike '*\\data\\postmaster.pid' } |
  Sort-Object FullName |
  ForEach-Object {
    $relative = $_.FullName.Substring((Resolve-Path $source).Path.Length).TrimStart('\\')
    "{0}|{1}|{2}" -f $relative,$_.Length,(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash
  } | Set-Content .local/runtime/main-runtime-source-manifest.txt
```

该命令在服务停止后执行，并排除 `data/postmaster.pid`。在服务仍运行时，仅用 SQLAlchemy 的只读查询记录 `source_definitions`、`operation_runs`、`raw_items`、`events` 四张表的行数；结果写入 JSON，不写入业务表。

- [x] **步骤 3：核对基线**

验收：基线文件存在；来源数据目录非空；来源、任务、RawItem、Event 计数均为非负整数。

### 任务 2：停止旧实例并复制数据目录

**文件：**
- 创建：`main/.local/postgres/**`（运行时数据，Git 忽略）
- 读取且保留：`.worktrees/raw-item-ingestion/.local/postgres/**`

**产物：** `main/.local/postgres` 是来源目录的完整副本；旧目录没有被修改。

- [x] **步骤 1：受控停止主分支网页和 Worker**

读取 `main/.local/runtime/main-web.pid` 与 `main/.local/runtime/main-worker.pid`，仅停止这两个仍存活且命令行工作目录为主分支的进程。不得停止 `8765` 上属于其他保留工作树的网页进程。

- [x] **步骤 2：停止旧工作树拥有的 PostgreSQL 服务**

运行：

```powershell
uv run newsradar db stop
```

从 `D:\codex_project_work\news_codex\.worktrees\raw-item-ingestion` 执行；随后轮询 `55432`，直至不再监听。

- [x] **步骤 3：生成稳定来源清单**

在旧服务已经停止后执行任务 1 的清单命令；跳过相对路径 `data/postmaster.pid`，并将其 SHA-256 写入 `.local/runtime/main-runtime-source-manifest.txt`。此时来源目录不再变化，可作为复制校验依据。

- [x] **步骤 4：复制数据目录**

运行：

```powershell
Copy-Item -LiteralPath 'D:\codex_project_work\news_codex\.worktrees\raw-item-ingestion\.local\postgres' `
  -Destination 'D:\codex_project_work\news_codex\.local' -Recurse -Force
```

前置条件：`main/.local/postgres` 不存在。任何复制错误立即停止，旧目录保持不变。

- [x] **步骤 5：验证副本**

使用任务 1 的清单比较文件相对路径、大小和 SHA-256。任何差异均不启动主分支数据库。

### 任务 3：由主分支接管并验证数据库

**文件：**
- 修改：`main/.local/runtime/main-runtime-migration-baseline.json`（追加切换后结果，Git 忽略）

**产物：** `main` 启动 PostgreSQL 并满足迁移与数据计数基线。

- [x] **步骤 1：从主分支启动数据库**

运行：

```powershell
uv run newsradar db start
uv run alembic current
uv run alembic check
```

预期：端口 `55432` 监听；版本为 `20260712_0008 (head)`；无待生成迁移。

- [x] **步骤 2：比较数据计数**

重新执行任务 1 的只读计数查询；来源、任务、RawItem、Event 计数必须和迁移前基线一致。

- [x] **步骤 3：失败回滚（未触发）**

若启动或计数验证失败：停止主分支数据库，保留副本供诊断；从旧工作树重新启动旧服务；不得删除任何目录。

### 任务 4：恢复主分支运行时并记录验收

**文件：**
- 创建：`reports/main-runtime-ownership-verification.md`

**产物：** 主分支 Web/Worker 正常运行，验收报告说明切换结果、回滚保留状态和已知限制。

- [x] **步骤 1：启动主分支网页和 Worker**

在端口 `8765` 被保留实例占用时使用隔离端口，但必须明确记录该端口；Worker 使用唯一标识。

- [x] **步骤 2：执行只读运行验收**

检查 `/`、`/events`、`/operations` 返回 HTTP 200；检查 Web 和 Worker 进程存活，日志不含 `Traceback`、`ERROR` 或 `CRITICAL`。

- [x] **步骤 3：写入中文验收报告并验证工作树**

运行：

```powershell
uv run ruff check src tests migrations
git diff --check
git status --short --untracked-files=no
```

验收：报告不含机密；已跟踪改动只包含报告；旧工作树及其本地文件仍存在。
