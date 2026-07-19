# Windows 桌面生命周期与图标一致性设计

## 目标

让 Windows 桌面版具备可预测的启动、隐藏和退出行为，并让 EXE、任务栏、Alt+Tab 与系统托盘使用同一套 News Codex 图标。修复范围不改变新闻抓取、日报、数据库或手动命令启动方式。

## 已确认的用户语义

- 点击窗口右上角关闭按钮：仅隐藏到系统托盘，Web 与 Worker 继续运行。
- 点击托盘“退出 News Codex”：退出桌面窗口，并停止该窗口启动的 Supervisor、Web 和 Worker 完整进程树。
- 启动桌面版时：只清理与当前 `NewsCodex.exe` 路径相同、父进程已经消失的内部 Web/Worker 遗留进程。
- 通过 `uv run newsradar serve` 等命令手动启动的 Python 服务视为外部服务；桌面版可以连接，但不得停止或清理它。
- 如果另一个仍然存活的 News Codex 实例拥有服务进程树，新窗口把它视为外部服务，不抢占、不终止。

## 方案选择

采用轻量的进程树管理模块和共享图标模块。

未采用只调用 `process.terminate()` 的最小方案，因为 Windows 会直接终止 Supervisor，无法保证它执行清理逻辑，正是当前 Web/Worker 遗留的原因。未采用 Windows Service 或原生 Job Object，因为这会显著扩大安装、权限和维护范围。

进程管理使用 `psutil`：它只在启动清理和明确退出时执行一次有界进程枚举或树终止，不做后台轮询，不增加常驻 CPU 负担。它也提供稳定的 PID、父子关系、可执行文件路径和递归子进程能力，便于精确限制清理范围。

## 组件设计

### 进程树管理

新增 `newsradar.desktop.processes`，职责限定为：

1. 根据 Supervisor PID 获取当前仍存活的递归子进程。
2. 先请求终止整棵自有树，在有限等待后强制结束未退出进程。
3. 启动时查找同一路径 `NewsCodex.exe` 的孤立内部进程。只有命令行包含 `--news-codex-internal`、角色为 `web` 或 `worker`、且记录的父进程已不存在时，才允许清理。
4. 路径比较使用 Windows 不区分大小写的规范化绝对路径；访问被拒绝、进程竞态消失等情况转为有界诊断，不影响其他进程。

`DesktopController` 继续决定服务是 `running`、`external_running`、`stopped` 或 `failed`。它在首次启动服务前执行一次孤儿清理；退出自有服务时调用进程树终止器。外部服务路径保持现有“不停止”行为。

### 图标统一

新增 `newsradar.desktop.icon`，提供一个按尺寸生成 RGBA 图像的函数。图形仍沿用当前 EXE 的深色圆角底、蓝色轮廓、中心蓝色圆形和播放标记。

- `tools/build_windows_desktop.py` 使用该函数生成多尺寸 ICO 并嵌入 EXE。
- `PyWebviewTrayUi` 使用同一函数生成 64×64 托盘图标。
- 不再在托盘代码中维护第二套简化圆点绘制逻辑。

## 数据流与生命周期

```text
双击 NewsCodex.exe
  -> 一次性清理同路径孤立内部进程
  -> 探测 8767
     -> 无服务：启动 Supervisor -> Web + Worker
     -> 有外部服务：只连接，不取得所有权
  -> 显示窗口与统一托盘图标

窗口关闭
  -> 隐藏窗口，服务继续

托盘退出
  -> 若拥有 Supervisor：终止 Supervisor + Web + Worker 完整树
  -> 若连接外部服务：保留外部服务
  -> 停止托盘并销毁窗口
```

## 错误处理与诊断

- 进程枚举、读取命令行和终止均捕获 `NoSuchProcess`、`AccessDenied` 与超时。
- 只对精确匹配当前 EXE 路径和内部命令标记的孤儿执行清理。
- 自有进程树停止失败时，控制器返回中文 `failed` 状态，不销毁窗口，方便用户重试或查看 `.local/logs/news-codex-desktop.log`。
- 所有等待有固定上限；不新增无限循环或高频后台轮询。

## 测试与验收

- 测试驱动覆盖：孤儿识别、路径隔离、外部 Python 服务保护、活跃父进程保护、完整树终止、超时强制结束、控制器退出状态。
- 图标测试覆盖：构建脚本与托盘均调用共享图标函数，输出尺寸和关键像素一致。
- 运行完整 pytest 与 Ruff。
- 重新打包 EXE，在独立端口验证 Web/Worker 启动；实际点击窗口关闭确认仅隐藏，再点击托盘退出确认该 EXE 的桌面、Supervisor、Web、Worker 全部消失且 8767 不再监听。
- 验收期间不读取或输出 `.env` 内容，不触碰用户保留的报告文件。

## 非目标

- 不把 News Codex 安装为 Windows 系统服务。
- 不终止手动运行的 Python、PostgreSQL 或其他程序。
- 不实现跨会话远程控制、自动更新或安装包。
- 不改变日报生成、定时任务、抓取和数据库结构。
