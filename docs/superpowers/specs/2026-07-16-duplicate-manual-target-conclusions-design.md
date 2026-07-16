# 重复人工目标结论收口设计

日期：2026-07-16  
状态：用户已批准设计方向，等待书面设计复核

## 背景

当前 187 个 Target 中仍有 17 个 `manual_only`。其中部分是同一官方身份下的历史成对目录目标：一个 `primary`，一个 `AI discovery`。两者使用相同 `official_identity_url`，却分别显示相同的“只能人工查看”，导致网页把同一个外部问题重复计入“需要用户操作数”。

本阶段修正结论口径，不删除 Target，不修改历史 FetchRun、探测或 RawItem，也不新增抓取器。

## 目标

对于同一官方身份下的重复目录目标，只允许一个目标承载当前外部阻塞与下一步动作。其余重复项显示唯一、中文、可理解的“重复目录项，由主目标统一处理”，归入“近期不处理”。

该规则不能把重复项算作实际成功，也不能掩盖主目标的真实外部阻塞。

## 已知范围

当前需要应用该口径的同身份目录组包括：

- Axios Technology：`universe-axios-1` / `universe-axios-2`
- Discord Communities：`universe-discord-1` / `universe-discord-2`
- Forbes Innovation：`universe-forbes-1` / `universe-forbes-2`
- Fortune Technology：`universe-fortune-1` / `universe-fortune-2`
- Semafor Technology：`universe-semafor-1` / `universe-semafor-2`
- Washington Post Technology：`universe-washington-post-1` / `universe-washington-post-2`

已经由成功目标覆盖的 Ben’s Bites、The Cognitive Revolution、No Priors、Reuters 和 TLDR AI 继续使用现有“已由同一官方目标覆盖”结论，本设计不改变该规则。

## 主目标选择规则

同一规范化 `official_identity_url` 下存在多个 Target 时，按以下稳定顺序选择承载问题的主目标：

1. 本目标已有成功或 `no_change` FetchRun。
2. 本目标登记了无需凭据、无需人工审批的公开候选路径。
3. `target_type` 为 `publisher_feed`，优先于 `search_query`。
4. ID 以 `-1` 结尾，优先于 `-2`。
5. 最后按 Target ID 字典序，保证结果稳定。

成功 FetchRun 仍优先触发现有“已由同一官方目标覆盖”逻辑。只有同组没有成功 FetchRun 时，才使用“重复目录项”逻辑。

Washington Post 因 `universe-washington-post-1` 已登记公开 RSS，应由该目标继续显示“已有公开路径待验收”；`universe-washington-post-2` 显示重复目录项。

## 结论模型

为结论输入增加可选的 `managed_by_target_id`。当它存在且没有更高优先级的外部禁止或成功覆盖规则时，返回：

- `code`: `duplicate_catalog_target`
- `bucket`: `deferred`
- `label`: `重复目录项`
- `reason`: `与目标 <主目标 ID> 使用同一官方身份，当前问题和验收由主目标统一承载。`
- `next_action`: `保留历史目录记录；不要重复申请权限、开发抓取器或重复入库。`

外部禁止规则仍具有最高优先级：`requires_payment`、`unavailable` 和 `requires_approval` 不得被重复关系隐藏。当前适用组均为 `manual_only + catalog_only`，因此不会覆盖这些外部禁止状态。

## 查询与数据流

`DashboardQueryService` 在一次批量查询中读取当前 Target 的官方身份、访问方法和成功 FetchRun，建立规范化官方身份分组。对每组计算唯一主目标 ID，并把该 ID 传给同组其他未成功 Target 的结论输入。

规范化只允许：

- scheme 和 host 转为小写；
- 去掉 path 末尾斜杠；
- 去掉 fragment；
- 保留非敏感 query，避免把两个实际不同入口错误合并。

不得使用名称模糊匹配、Provider ID 相同或 URL 主域名相同来推断重复关系。

## 网页与汇总

现有目标页面无需新增列。`当前结论`、`中文原因和下一步动作` 直接显示新结论。

汇总行为：

- 总目标数保持 187。
- 实际成功数不变。
- 每个重复目录项从“需要用户操作”移动到“近期不处理”。
- 主目标继续保留真实结论，因此每个外部问题仍至少有一条可执行记录。

## 安全边界

- 不删除、归档或合并数据库 Target。
- 不修改来源 YAML 的可用性或抓取批准状态。
- 不发起网络请求。
- 不读取或输出 `.env`。
- 不将重复目录项视为抓取成功、能力已验收或来源合法。
- 不让 MiniMax 参与主目标选择或来源启用判断。

## 测试策略

严格测试驱动：

1. 结论单元测试：重复项得到 `duplicate_catalog_target + deferred`，且不会增加实际成功。
2. 查询测试：同 URL 的 primary/search pair 只保留一个需要用户操作；选择规则稳定。
3. 公开候选优先测试：Washington Post 模型中 RSS 主目标胜过 HTML 搜索占位项。
4. 成功覆盖回归：已有成功 FetchRun 时仍显示 `covered_by_successful_target`，不降级为普通重复项。
5. URL 边界测试：不同 path 或 query 不合并；末尾斜杠可以合并。
6. 汇总测试：四个 bucket 总和等于总目标数，实际成功数不变。
7. 完整 pytest、Ruff 与真实 8766 网页验收。

## 验收标准

- 187 个目标均保留。
- 6 组当前重复人工目标各自只有一个目标承载实际问题。
- Washington Post 主目标继续显示公开 RSS 待验收。
- 重复项明确显示主目标 ID 和不重复开发的下一步。
- 实际成功数不因本变更增加。
- 网络、Worker 和 RawItem 数据均不被修改。

