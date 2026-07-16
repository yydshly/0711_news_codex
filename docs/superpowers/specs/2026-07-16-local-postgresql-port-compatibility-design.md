# 本机 PostgreSQL 端口兼容设计

## 背景

News Codex 的项目专用 PostgreSQL 固定使用 `127.0.0.1:55432`。当前 Windows 的 TCP 保留范围包含 `55432`，因此 PostgreSQL 启动时被系统拒绝绑定。项目的 `.local/postgres/data` 已存在，不能通过重建集群或改连另一套 PostgreSQL 服务绕过问题。

## 目标

- 允许项目专用 PostgreSQL 使用本机可用端口，默认保持 `55432` 兼容。
- 对 Windows 保留端口给出可操作的中文错误信息。
- 通过受控命令把现有项目实例切换到 `55232`，同步数据库配置和本机 `.env`，不删除或重建数据目录。
- 保持 `db init`、`db start`、`db status`、`db stop`、`db repair` 的端口一致性。

## 非目标

- 不修改 Windows 的端口保留策略。
- 不尝试接管 `5432` 上的其他 PostgreSQL 服务。
- 不提交 `.env`、密码或数据库数据。
- 不改变来源抓取、事件处理或网页产品逻辑。

## 设计

### 端口解析

新增 `NEWSRADAR_POSTGRES_PORT` 环境变量。有效值为 `1024–65535` 的整数；未设置时使用兼容默认值 `55432`。`LocalPostgresManager` 在构造时持有解析后的端口，所有 URL、`pg_ctl`、`pg_isready`、端口占用检查和配置写入均使用该实例值，避免模块级常量与 `.env` 脱节。

### Windows 预检

启动或初始化前，在 Windows 上读取 TCP 排除端口范围。目标端口落入范围时，拒绝启动并提示：该端口为系统保留、应设置 `NEWSRADAR_POSTGRES_PORT=55232` 后执行 `newsradar db repair`。查询失败不阻塞非 Windows 或未知环境；实际绑定失败仍保留 PostgreSQL 原始错误。

### 迁移与修复

`db repair` 检测已初始化集群的目标端口是否与 `postgresql.conf` 不同。若不同且实例未运行：原子地更新项目专用配置中的 `port`，并使用现有密码改写 `.env` 中的 `DATABASE_URL` 与 `NEWSRADAR_POSTGRES_PORT`。数据目录、角色、数据库和日志保持原样。

若实例正在运行且请求切换端口，命令拒绝并要求先执行 `db stop`，避免运行中配置与连接地址分裂。

### 验证

- 单元测试覆盖默认端口、合法与非法覆盖、URL 写入、命令参数和配置变更。
- Windows 范围解析使用可注入命令输出测试；非 Windows 不执行该查询。
- 真实环境按顺序：设置 `NEWSRADAR_POSTGRES_PORT=55232`，运行 `db repair`、`db start`、`db status`、Alembic 当前版本和 v1.5 PostgreSQL 验收。

## 风险与回滚

端口切换只更改本地配置文本，可回滚为旧端口；但旧端口在当前系统仍不可用。若 `55232` 后续也被占用或保留，选择另一未监听、未保留的高位端口并重复修复。任何修复前不会删除 `.local/postgres` 或 `.env`。
