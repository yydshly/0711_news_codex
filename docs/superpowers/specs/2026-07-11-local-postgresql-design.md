# News Codex 项目独立 PostgreSQL 设计

## 目标

在不修改现有 Windows PostgreSQL 服务、不使用 Docker 的前提下，为 News Codex
建立可重复启动的本机 PostgreSQL 18 运行环境，并完成来源注册表迁移、同步和探测历史落库。

## 选择

使用 PostgreSQL 已安装程序创建项目独立集群，监听 `127.0.0.1:55432`。不复用当前
停止且密码未知的系统集群，也不注册新的 Windows 服务。

## 本地文件与秘密

- 数据目录：`.local/postgres/data`
- 日志目录：`.local/postgres/log`
- 项目环境：`.env`
- `.local/` 和 `.env` 必须由 Git 忽略。
- 数据库密码随机生成，只写入 `.env`；初始化使用的临时密码文件在完成后立即删除。
- 日志、命令输出、源码和数据库业务表不得记录数据库密码或 MiniMax API Key。

## 数据库与生命周期

- 数据库角色：`newsradar`
- 数据库名称：`newsradar`
- 连接地址：`127.0.0.1:55432`
- 认证方式：SCRAM-SHA-256
- 提供 PowerShell 命令管理 `init`、`start`、`status` 和 `stop`。
- `init` 必须幂等：已有合法集群和 `.env` 时不得重新生成密码或删除数据。
- `start` 只启动项目集群；不得启动、停止或修改 `postgresql-x64-18` 系统服务。

## 初始化数据流

1. 定位 PostgreSQL 18 的 `initdb`、`pg_ctl` 和 `psql`。
2. 创建 Git 忽略的本地目录并生成数据库密码。
3. 初始化项目集群，绑定回环地址和端口 `55432`。
4. 启动项目集群，创建 `newsradar` 数据库。
5. 写入 `.env` 的 `DATABASE_URL`，保留 MiniMax 和可选来源凭据为空。
6. 执行 `alembic upgrade head`。
7. 执行 `newsradar sources sync`，写入 27 个来源定义及首个版本。
8. 执行一次 `sources probe --all`，将结果和样本持久化到 PostgreSQL。

## 错误处理

- 端口已占用时立即失败并说明占用端口，不改用随机端口。
- PostgreSQL 程序、数据目录或 `.env` 状态不一致时停止并给出修复指引。
- 单个来源探测失败仍记录失败结果，不中断批次。
- 网络限流、缺少 Reddit OAuth 等属于来源状态，不视为数据库初始化失败。

## 验收

- 管理脚本重复执行安全，且不会影响系统 PostgreSQL 服务。
- `pg_isready` 对 `127.0.0.1:55432` 返回可用。
- Alembic 版本为最新迁移。
- `source_definitions` 中存在 27 条定义，每个定义至少有一个版本。
- `source_probe_runs` 和 `source_probe_samples` 存在真实探测记录。
- `ruff`、完整 pytest 和来源 YAML 校验通过。
- Git 状态中不出现 `.env`、数据库数据、日志或密码。

## 非目标

- 不配置 Windows 自动启动服务。
- 不实现后台常驻调度器。
- 不增加 Docker、前端或新闻摘要。
- 不要求 MiniMax、Reddit、YouTube 等可选凭据即可完成本阶段验收。
