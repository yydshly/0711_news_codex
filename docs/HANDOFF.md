# News Codex 项目交接手册

最后核验：2026-07-19

运行能力基线：`4414877`（文档提交可以更新，当前 Git 状态以命令查询为准）

正式项目：`D:\codex_project_work\news_codex`

正式网页：<http://127.0.0.1:8767/>

> 本文档是当前项目状态、操作命令和后续工作的统一入口。动态数量以数据库和网页为准，不要用历史报告数字替代当前事实。

## 1. 现在做什么

项目已经进入可日常使用后的稳定观察期。当前重点不是继续扩充来源或重写已有模块，而是让正式桌面程序连续运行 1–3 天，观察每日自动日报的真实表现。

每天重点检查：

- 自动日报是否按时启动并进入终态；
- 今日抓取、事件和日报条目数量是否合理；
- 同一天后生成的日报是否包含前面报告的有效内容；
- 是否出现明显遗漏、重复或同一事件错误拆分；
- 决策简报和情报全览是否体现不同的信息密度；
- 中文增强、中文审核建议和证据评价是否具体；
- 决策版音频是否正常，全览音频是否能按需生成；
- CPU、内存、窗口隐藏、托盘退出和重新启动是否正常。

稳定观察期间不要因为单日条目少就立即扩大时间窗口、重复执行全量来源探测或重新设计日报管线。先查看抓取批次、RawItem、事件、自动日报任务和过滤理由。

## 2. 已经完成什么

### 来源和采集

- Provider 与 Target 分层目录、访问方式、凭据、审批、费用和人工状态；
- 来源校验、同步、探测、研究和中文状态页面；
- 正式抓取、RawItem 持久化、原始 URL、发布时间和来源归属；
- 持久任务队列、有限重试、取消、心跳、恢复和结构化诊断；
- 单个来源失败不会阻塞整批任务；
- 不使用 Cookie 爬虫、验证码绕过、代理规避或高风险登录态抓取。

### 事件和证据

- RawItem 去重、事件聚类、证据根、重复候选和人工审查；
- 跨来源安全合并和同一事件版本记录；
- `hotspot`、`signal`、`audit_only` 等不同质量层级；
- MiniMax 可用于受约束的中文增强，但规则管线在模型不可用时仍能完成。

### 中文日报

- 决策简报和情报全览两种视图；
- 中文概述、中文审核建议、中文证据评价和原文链接；
- 同日累计、修订版、人工调整、归档、置顶、回收站和永久删除；
- 决策版音频，以及按需生成的全览音频；
- 自动日报启用、暂停、立即运行、取消、运行详情和历史记录；
- 多次生成、失败后重试和同日累计逻辑。

### Windows 桌面程序

- 正式 `NewsCodex.exe`、窗口、系统托盘和开机启动管理；
- 标题栏关闭只隐藏窗口，托盘“退出 News Codex”才退出整套程序；
- Desktop、Supervisor、Web、Worker 的自有进程树清理；
- PID 复用、进程身份不可访问、孤儿进程和启动竞态的失败关闭保护；
- 单实例保护：重复双击只显示“已在运行”提示，不创建第二套后台；
- EXE、任务栏、Alt+Tab 和托盘使用同一图标源；
- 正式构建、完整 pytest、Ruff、HTTP 200 和 Windows 实机验收已完成。

### 仓库整理

- 本轮文档开始前，本地 `main` 已推送并与 `origin/main` 同步，运行能力基线为 `4414877`；
- 历史临时验收目录、构建缓存和 13 个已合并 worktree 已清理；
- `D:\codex_project_work` 下只保留正式 News Codex 和其他明确独立产品；
- 用户报告仍保持未提交，没有被混入代码提交。

## 3. 卡在哪里

当前没有阻断正式使用的已知代码问题。剩余事项分为以下几类：

### 需要真实运行验证

自动日报的长期完整性不能仅由单次测试证明。需要连续观察真实每日运行，判断来源时效、重复率、事件质量、决策版与全览版差异以及音频稳定性。

### 尚未实现的产品能力

正式分享/导出能力尚未实现。当前可以在本地网页查看日报和原文，但没有面向外部发送的受控分享页、导出文件或分享链接。

### 外部约束

部分来源仍受平台凭据、官方审批、付费、人工查看或不可用状态约束。这些不是通过绕过登录或反爬就应该“修复”的代码问题。

### 已归档的历史状态

截至 2026-07-20，主工作区已恢复干净；九个旧 worktree 的未提交文件已完整归档到
`.local/worktree-archives/2026-07-20-worktree-cleanup/`，该目录不进入 Git。

`codex/expert-source-audit` 的 6 个提交已在 2026-07-20 审查：其“保持人工状态”的结论已被主干后续的官方 RSS/Sitemap 验证取代，不能直接合并。
完整历史已归档到 `.local/git-archives/2026-07-20-expert-source-audit.bundle`，本地分支和 worktree 均已移除；如需追溯，可从该 bundle 恢复审查。

## 4. 下一步做什么

建议顺序：

1. 连续运行 1–3 天，完成每日自动日报观察清单；
2. 只修复观察中能复现、能定位、影响实际使用的问题；
3. 稳定观察通过后，单独设计“分享/导出 MVP”；
4. 日常诊断输出使用 `.local/reports/`；只有明确要版本化的验收快照才写入 `reports/`；
5. 若需要追溯专家来源旧审核结论，从 `.local/git-archives/2026-07-20-expert-source-audit.bundle` 创建临时审查分支，不直接恢复到主干；
6. 每个大里程碑后更新本文档的日期、提交、当前限制和下一步。

分享/导出 MVP 不应重新实现日报生成。它应消费现有日报快照，明确公开范围、脱敏规则、原文链接、音频是否包含以及撤销方式。

## 5. 哪些坑不要再踩

### 数据和来源

- 不要把“已注册”“能力探测成功”或“间接发现”写成“已真实抓取成功”；
- 不要根据旧报告数字判断当前数据库；先查网页和数据库；
- 不要为了验证一个日报问题重新探测全部来源；
- 不要因为 24 小时数据少就直接扩展到 72 小时；先查 RawItem、事件和过滤链路；
- 不要把聚合页、转载、社交互动或未解析原始媒体的链接当作独立证据；
- 不要绕过登录、Cookie、验证码、付费墙或平台审批；
- 不要让 MiniMax 决定来源是否合法、是否启用或是否构成证据。

### 日报和音频

- 不要把决策简报和情报全览做成两个相同列表；决策版应更短、更明确，全览版应保留更多有效信号；
- 不要因为规则回退就输出千篇一律的中文审核建议；应保留可定位的回退原因；
- 不要让一次失败永久阻断当天后续重试；
- 不要把同一天多次生成理解为互相独立，后续日报应遵循同日累计语义；
- 不要默认生成全览音频；全览音频通常按需生成；
- 不要把自增日报编号或任务编号当成故障，编号持续增长是正常数据库行为。

### Windows 和进程

- 不要通过模糊进程名或裸 PID 批量结束进程；必须验证 EXE 路径和创建时间身份；
- 不要停止手动 Python 服务、PostgreSQL、Codex 或其他 EXE 路径；
- 不要在正式 EXE 运行时覆盖 `dist\NewsCodex`；先从托盘退出；
- 不要把标题栏关闭当作退出，标题栏关闭只隐藏窗口；
- 不要把正常的四角色进程误认为四套软件；正常结构是一个桌面进程和三个内部角色；
- 重复启动时可能短暂出现第五个提示进程，关闭提示后不会保留第二套后台；
- 不要同时保留多个旧验收 EXE，日常只使用正式目录。

### Git 和工作目录

- 不要读取、输出或提交 `.env`；
- 不要提交 `.local/`、数据库、`build/`、`dist/`、音频产物或临时审查 diff；
- 不要在 `D:\codex_project_work` 下创建新的 News Codex 同级 worktree；
- 所有新 worktree 只放在项目内 `.worktrees/`；
- 不要删除含未提交内容或未合并提交的 worktree；
- 合并后要及时 `git worktree remove` 和 `git worktree prune`；
- 不要使用强制推送；
- 不要把用户报告和功能代码放进同一个提交。

## 6. 启动、目录、打包和注意事项

### 重要目录

| 目录 | 用途 | 是否可删除 |
|---|---|---|
| `D:\codex_project_work\news_codex` | 正式项目根目录 | 否 |
| `dist\NewsCodex` | 正式 Windows 程序 | 重新打包前可替换，但不能在运行时删除 |
| `providers\` | Provider 审核目录 | 否 |
| `sources\` | Target 和来源审核目录 | 否 |
| `.local\postgres\` | 项目本地 PostgreSQL 数据 | 绝对不能当缓存删除 |
| `.local\logs\` | 本地运行日志 | 排障后按策略处理 |
| `reports\` | 用户报告与历史验收材料 | 未经确认不得修改或删除 |
| `.worktrees\` | 隔离开发工作树 | 仅在已合并且干净时通过 Git 移除 |
| `build\` | PyInstaller 构建缓存 | 停止构建后可删除，会自动重建 |

### 首次安装或依赖同步

在 PowerShell 中执行：

```powershell
Set-Location D:\codex_project_work\news_codex
uv sync --extra dev --extra research
```

`.env` 只从 `.env.example` 创建并由用户维护。不要在终端输出、报告或提交中展示其内容。

### 数据库

```powershell
uv run newsradar db init
uv run newsradar db start
uv run newsradar db status
uv run alembic upgrade head
```

停止和确定性修复：

```powershell
uv run newsradar db stop
uv run newsradar db repair
```

`db repair` 只用于确定性局部状态修复，不会替代数据库备份。不要手工删除 `.local\postgres\`。

### 同步审核目录

```powershell
uv run newsradar providers validate --root providers
uv run newsradar providers sync --root providers
uv run newsradar sources validate --root sources
uv run newsradar sources sync --root sources
```

同步目录不会自动证明来源当前可抓取，也不会自动把受限来源改为可用。

### 开发态启动

推荐同时启动 Web 和 Worker，并统一使用正式端口：

```powershell
uv run newsradar serve --host 127.0.0.1 --port 8767
```

桌面开发入口：

```powershell
uv run newsradar desktop run --port 8767
```

开发入口运行在 Python 下，适合调试；日常使用正式 EXE。

### 正式 Windows 程序

正式文件：

```text
D:\codex_project_work\news_codex\dist\NewsCodex\NewsCodex.exe
```

可以双击，或运行：

```powershell
Start-Process `
  -FilePath 'D:\codex_project_work\news_codex\dist\NewsCodex\NewsCodex.exe' `
  -WorkingDirectory 'D:\codex_project_work\news_codex\dist\NewsCodex'
```

常用网页：

- 首页：<http://127.0.0.1:8767/>
- 中文日报：<http://127.0.0.1:8767/daily-reports>
- 回收站：<http://127.0.0.1:8767/daily-reports/trash>
- 自动日报具体运行：`http://127.0.0.1:8767/daily-autopilot/<run_id>`

标题栏关闭只隐藏窗口。需要彻底退出时，从系统托盘选择“退出 News Codex”。

### Windows 登录启动

```powershell
uv run newsradar desktop autostart-enable
uv run newsradar desktop autostart-status
uv run newsradar desktop autostart-disable
```

正式打包版启用登录启动时，Windows 记录的是 `NewsCodex.exe`；移动或删除正式目录后应重新配置。

### 代码验证

```powershell
uv run ruff check .
uv run pytest -q
```

完整 pytest 通常需要数分钟。文档、配置或依赖变化后仍应根据风险运行相应验证，不要把“此前通过”当作当前证据。

### Windows 打包

先从托盘退出正式程序，确认没有正式路径进程正在使用文件，然后执行：

```powershell
uv run --extra dev --extra research python tools\build_windows_desktop.py
```

成功输出：

```text
Built: dist/NewsCodex/NewsCodex.exe
```

打包后重新启动正式 EXE，并验证：

```powershell
Invoke-WebRequest `
  -Uri 'http://127.0.0.1:8767/daily-reports' `
  -UseBasicParsing `
  -TimeoutSec 5
```

预期 HTTP 200。再按正式 EXE 路径检查进程树，应包含：

```text
Desktop -> Supervisor -> Web + Worker
```

不要为了释放构建锁而结束所有 `python.exe`、`NewsCodex.exe` 或占用 8767 的未知进程。先核对可执行文件路径、命令行和父子关系。

### Git 分支和 worktree

开始工作：

```powershell
Set-Location D:\codex_project_work\news_codex
git fetch origin
git worktree add '.worktrees\<task-name>' `
  -b 'codex/<task-name>' main
```

完成、合并并验证后：

```powershell
git worktree remove '.worktrees\<task-name>'
git worktree prune
```

删除前必须确认：分支已经合并、工作树没有真实未提交内容、没有进程从该目录运行。不要用资源管理器直接删除已注册 worktree。

## 7. 常见问题定位

### 网页打不开

1. 运行 `uv run newsradar db status`；
2. 检查正式程序是否正在运行；
3. 检查 8767 是否监听；
4. 查看 `.local\logs\`；
5. 不要立即删除数据库或重新初始化项目。

### 自动日报失败

依次查看中文日报页、自动日报运行详情、抓取批次、RawItem、事件和任务日志。先定位失败阶段，再决定重试。不要因为第一次失败就认为当天无法再次生成。

### 日报条目过少

先区分：没有抓到 RawItem、没有形成事件、事件被合并、事件被质量过滤、或日报选择层过滤。决策版少不代表全览版也应该少；全览版仍只包含通过最低有效性门槛的内容。

### 中文增强回退

“规则回退”表示模型响应不可用、格式无效或不是有效简体中文。规则管线仍会完成，但应通过日志定位具体回退原因，不要把规则回退误认为日报整体失败。

### 音频很慢或不存在

先区分决策版和全览版音频。全览音频通常按需生成，篇幅更长、耗时更高。检查任务状态和 MiniMax T2A 诊断，不要重复点击制造并发任务。

### 看见多个 NewsCodex 进程

正常正式运行会有四个角色进程，不是四套应用。重复双击会短暂出现提示进程，但不会创建第二套 Supervisor、Web 或 Worker。若出现多个完整窗口或托盘，先检查是否启动了旧目录中的 EXE。

## 8. Handoff 更新清单

每个大里程碑结束后更新以下内容：

- 最后核验日期；
- `main` 与 `origin/main` 提交；
- 当前正式运行状态和验证命令；
- “现在做什么”“卡在哪里”“下一步做什么”；
- 新确认的限制、故障模式和禁止动作；
- 新增或已清理的保留 worktree。

不要记录：

- `.env` 内容或任何密钥；
- 临时 PID；
- 未经当前数据库确认的历史数量；
- 模型完整响应、来源正文或敏感日志；
- 尚未验证的“已经完成”结论。

## 9. 开发效率与流程分级

开始任务前先判断任务等级，流程必须与风险匹配，不能因为工具齐全就默认采用最重流程。

### L0：解释、状态查询和只读审查

适用：回答问题、解释现状、读取 Git/数据库/网页状态。

- 不创建分支或 worktree；
- 不写规格和实施计划；
- 不运行与问题无关的完整测试；
- 直接给出基于证据的答案。

### L1：文档和不改变运行行为的配置

适用：README、Handoff、注释、纯文案和低风险配置说明。

- 主工作区干净时可以直接使用短分支；主工作区有用户改动时使用一个隔离 worktree；
- 直接编辑目标文件，不先创建规格、计划或子 Agent；
- 只验证链接、命令、格式、编码、Ruff 和 Git 范围；
- 一个提交、一次审阅、一次合并确认即可。

### L2：局部功能或可复现缺陷

适用：单模块功能、明确 bug、有限 API 或页面修改。

- 使用独立分支和 worktree；
- 先复现，再用针对性测试驱动修复；
- 运行相关测试和 Ruff；
- 完成一次独立代码审查；
- 只有风险扩大时才补完整设计。

### L3：跨模块、高风险和长期状态变更

适用：数据库迁移、进程生命周期、任务恢复、来源合规、跨来源合并和大规模架构修改。

- 先写设计与实施计划；
- 按里程碑执行，可使用多个 Agent；
- 每个里程碑审查；
- 运行完整 pytest、Ruff、构建和真实验收；
- 未确认不得合并或推送。

### 效率停止规则

- 用户明确说“只是简单文档”或“只需要解释”时，立即降级到 L0/L1；
- 单文件或双文件文档任务不得自动扩展为设计规格、实施计划和多 Agent 流程；
- 已有近期完整测试证据且本次不改代码时，不重复运行完整 pytest；
- 任何步骤如果不能降低当前任务的真实风险，就不应成为必经门槛；
- 一个简单任务连续需要多次确认，说明流程已经过重，应立即合并确认点；
- 优先交付用户可见结果，再记录必要的最小证据。
