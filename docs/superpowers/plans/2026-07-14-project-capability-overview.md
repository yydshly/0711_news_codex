# News Codex 项目能力总览实施计划

> **执行要求：** 按既定设计收口现有能力，不新增来源、不修改抓取协议、不新增数据库迁移。

**目标：** 将 `/sources` 建设为唯一的项目能力总览，让使用者在一个中文页面中看清来源目录、探测、真实抓取、RawItem、事件、MiniMax 和运行活动的实际状态。

**架构：** 新增独立的只读目录快照和能力投影查询层，通过现有 `DashboardQueryService` 接入 Web。YAML 负责当前目录真相，PostgreSQL 负责运行事实；页面只展示布尔配置状态和聚合结果，不执行抓取、模型调用或数据库写入。

**技术栈：** Python 3.12、FastAPI、SQLAlchemy 2、Jinja2、Pydantic 2、pytest。

---

## 任务 1：建立目录快照与能力查询投影

**文件：**

- 新建：`src/newsradar/web/capability_queries.py`
- 修改：`src/newsradar/web/queries.py`
- 新建：`tests/web/test_capability_queries.py`

**步骤：**

1. 先编写失败测试，覆盖 YAML/数据库一致与漂移、最新探测去重、成功抓取来源去重、RawItem/事件/模型/实体/Worker 活动统计和敏感配置布尔化。
2. 实现不可变 `CatalogSnapshot` 和 `CapabilityOverviewView`，由受限只读查询一次组装页面所需数据。
3. 仅把当前 YAML Target 计入当前能力；数据库残留 ID 只进入漂移提示。
4. 将 `succeeded` 与 `no_change` 都视为完成过真实抓取；Worker 心跳只描述近期任务活动。
5. 运行：`uv run pytest tests/web/test_capability_queries.py -q`。

## 任务 2：将 `/sources` 收口为中文项目能力总览

**文件：**

- 修改：`src/newsradar/web/app.py`
- 新建：`src/newsradar/web/templates/capability_overview.html`
- 修改：`src/newsradar/web/templates/base.html`
- 修改：`src/newsradar/web/static/styles.css`
- 修改：`tests/web/test_routes.py`

**步骤：**

1. 先补充失败路由测试，要求页面包含完整能力流水线、真实 RawItem/事件预览、目录漂移和 MiniMax 中文状态。
2. 为 `create_app` 增加可注入目录快照工厂；生产读取 `providers/` 与 `sources/`，测试使用内存快照。
3. `/sources` 渲染新的能力总览模板，保留 Provider、Target、探测、抓取、条目、事件、系统等既有下钻路由。
4. 页面严禁展示 API Key、数据库连接串、Cookie、Authorization、代理值或原始请求正文。
5. 增加桌面与窄屏样式，并将侧栏入口改为“项目能力”。
6. 运行：`uv run pytest tests/web/test_routes.py -q`。

## 任务 3：真实数据库与浏览器验收

**文件：**

- 按测试结果修正任务 1、2 的文件，不新增业务范围。

**步骤：**

1. 使用本地 PostgreSQL 环境运行 `/sources` 只读烟雾测试，确认实际统计来自现有数据库。
2. 记录访问前后关键表行数，证明浏览页面不产生数据库写入。
3. 在浏览器检查首屏结论、流水线、下钻链接、中文说明、窄屏布局和安全信息边界。
4. 运行完整质量门：`uv run ruff check .`、`uv run pytest -q`。

## 任务 4：最终审查、提交与合并

**文件：**

- 审查当前分支相对 `main` 的全部差异。

**步骤：**

1. 执行安全、正确性、查询边界和回归审查，修复所有阻断问题。
2. 提交计划与实现，保证当前分支工作区干净。
3. 检查主工作区是否干净，并确认 `main` 与当前分支没有分叉。
4. 仅在可安全快进时执行 `git merge --ff-only codex/source-failure-remediation`；不得强制、不删除任何工作树或本地运行数据。
5. 在合并后的 `main` 再运行必要验证，并报告本地分支、提交和远端差异；未经用户要求不推送。
