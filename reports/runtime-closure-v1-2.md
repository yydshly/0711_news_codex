# News Codex v1.2 本地运行闭环验收

验收日期：2026-07-15

## 结论

v1.2 的 MiniMax、Web、Worker、来源目录与安全健康波次已经形成可运行闭环。统一入口为：

```powershell
newsradar serve --host 127.0.0.1 --port 8766 --worker-id newsradar-local
```

## 真实运行证据

- PostgreSQL 已从迁移 `20260715_0015` 升级到 `20260715_0016`。
- YAML 当前目标 187 个，数据库当前目标 187 个，目录漂移为 0。
- 历史目标 2 个：`legacy-source`、`universe-youtube-1`；仅归档，没有删除历史证据。
- Worker `newsradar-local` 在线空闲，队列任务 0，运行中任务 0。
- MiniMax 中国区模型可见性检查 HTTP 200；结构化调用成功。
- MiniMax 快速模型为 `MiniMax-M2.7-highspeed`，深度模型为 `MiniMax-M2.7`。
- 本轮 MiniMax 调用记录输入 184 token、输出 972 token，耗时约 14.5 秒。
- 健康波次候选 37 个：32 个成功、5 个降级、0 个批次级中断。
- 数据库现有 RawItem 979 条；最新探测状态合计 99 个成功、10 个降级。

## 网页验收

- `/system`：数据库在线、Worker 在线空闲、MiniMax 已配置且最近调用成功。
- `/sources`：68 个有效 Provider、187 个当前 Target、2 个归档 Target，目录漂移提示消失。
- `/targets?catalog_state=archived`：仅显示两个历史目标。
- `/probes`：最新健康波次结果可见。
- `/events`：保留 86 个当前运行事件入口，历史事件快照仍可访问。

## 安全边界

- 报告、网页、日志和数据库不保存 API Key、Authorization、Cookie、提示词或模型响应正文。
- 健康波次不自动启用 HTML，且不回退到 Reddit Cookie、登录态或非官方绕过方式。
- 单来源异常被隔离；并发上限为 8，允许范围为 1–16。
- MiniMax 不参与来源合规与启用的最终决策；模型不可用时规则管线仍可运行。

## 剩余非阻塞事项

- 根目录 `.env` 当前尚未持久写入 MiniMax Key；本次统一运行进程从既有受保护本地配置继承 Key。重启机器或进程前，需要将 Key 安全配置到根目录 Git 忽略的 `.env`。
- 历史 Worker 记录仍显示 87 个过期心跳，这是审计历史，不代表 87 个当前故障进程。
- 健康波次中的 5 个降级来源应在后续来源迭代中逐项分析，不阻塞 v1.2 运行闭环。
