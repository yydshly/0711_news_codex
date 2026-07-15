# 来源目录全量刷新报告

## 验收元数据

- 代码提交基线：`84bd433`
- 数据库迁移：`20260715_0017 (head)`
- 实际操作：`827`（网页入队；Worker 执行）
- 验收提交：`851b949`（初始验收）、`922abbd`（原子进度）、`2bced73`（处理中取消）、`c0af90d`（过期租约恢复）、`46bc727`（最终证据归档）。
- 目录摘要：`7a9f36afe08d14eeca65d96105daf061f78ad57e2332ba7a8e80dabb8b05d206`，187 个冻结成员。

## 真实运行证据

- Web 入队立即返回，测得约 362 ms；网页进程未执行网络探测。
- Worker 运行中观测到进度从 `77/187` 到 `187/187`，并持续刷新心跳；终态没有遗留 `running` 成员。
- 内容通道 102/106 个成员保有三轮成功证据；内容、能力、目录三类保持互斥，分别为 106、20、61。
- 受控取消：操作 `828` 已在 `running` 状态请求取消，并终态为 `cancelled`；取消后的 Worker 正常退出。恢复及不重复探测由 PostgreSQL 验收测试覆盖。

## 受限与外部结果

- AP、Reuters、Bloomberg、Financial Times、WSJ 的内容成员均产生新的三轮内容结论；能力和目录成员未被误算作内容成功。
- DeepMind Blog 与 Hugging Face Blog 的实际结果为 `incomplete_fields`；Anthropic Bluesky 为 `no_content`；SEC EDGAR 为仅能力/审批结论；No Priors 仅目录/能力边界。
- 此次 GDELT 实测返回上游限流，保存为 `rate_limited`（没有伪造为 timeout）；Microsoft Research 有一项实际 `internal_error`，但未阻塞其余 186 个成员。
- 浏览器控制运行时报告“无可用浏览器”，故未能完成交互式控制台检查；临时 8767 服务仍以 HTTP 检查了页面、入队、详情、筛选参数与取消入口。

## 复现命令

```text
uv run alembic upgrade head
uv run newsradar providers sync
uv run newsradar sources sync
uv run newsradar sources refresh-plan
uv run pytest tests/acceptance/test_source_catalog_refresh_v1_4.py -q
uv run newsradar sources refresh-report 827 --output reports/source-catalog-refresh-v1-4.md
```

## 批次 ID
- 操作：827
- 状态：partial

## 目录摘要
- 摘要：7a9f36afe08d14eeca65d96105daf061f78ad57e2332ba7a8e80dabb8b05d206
- 冻结成员：187

## 完成度
- 187/187

## 三条通道
- 内容通道：106
- 能力通道：20
- 目录通道：61

## 结果码数量
- catalog_incomplete：61
- incomplete_fields：2
- internal_error：1
- missing_credentials：18
- no_content：1
- rate_limited：1
- requires_approval：1

## 内容三轮证据
- 已完成三轮证据的内容成员：102/106

## 能力解锁条件
- 补充凭据：18
- 完成平台审批：1

## 目录缺口
- anthropic-newsroom：catalog_incomplete
- universe-ap-1：catalog_incomplete
- universe-axios-1：catalog_incomplete
- universe-axios-2：catalog_incomplete
- universe-bens-bites-1：catalog_incomplete
- universe-bens-bites-2：catalog_incomplete
- universe-bloomberg-1：catalog_incomplete
- universe-brave-search-1：catalog_incomplete
- universe-brave-search-2：catalog_incomplete
- universe-cognitive-revolution-1：catalog_incomplete
- universe-cognitive-revolution-2：catalog_incomplete
- universe-discord-1：catalog_incomplete
- universe-discord-2：catalog_incomplete
- universe-event-registry-1：catalog_incomplete
- universe-event-registry-2：catalog_incomplete
- universe-facebook-1：catalog_incomplete
- universe-facebook-2：catalog_incomplete
- universe-financial-times-1：catalog_incomplete
- universe-forbes-1：catalog_incomplete
- universe-forbes-2：catalog_incomplete
- universe-fortune-1：catalog_incomplete
- universe-fortune-2：catalog_incomplete
- universe-gnews-1：catalog_incomplete
- universe-gnews-2：catalog_incomplete
- universe-google-trends-1：catalog_incomplete
- universe-google-trends-2：catalog_incomplete
- universe-instagram-1：catalog_incomplete
- universe-instagram-2：catalog_incomplete
- universe-linkedin-1：catalog_incomplete
- universe-linkedin-2：catalog_incomplete
- universe-mediacloud-1：catalog_incomplete
- universe-mediacloud-2：catalog_incomplete
- universe-newsapi-1：catalog_incomplete
- universe-newsapi-2：catalog_incomplete
- universe-no-priors-1：catalog_incomplete
- universe-no-priors-2：catalog_incomplete
- universe-nytimes-1：catalog_incomplete
- universe-nytimes-2：catalog_incomplete
- universe-producthunt-1：catalog_incomplete
- universe-producthunt-2：catalog_incomplete
- universe-reddit-1：catalog_incomplete
- universe-reddit-2：catalog_incomplete
- universe-reuters-1：catalog_incomplete
- universe-semafor-1：catalog_incomplete
- universe-semafor-2：catalog_incomplete
- universe-telegram-1：catalog_incomplete
- universe-telegram-2：catalog_incomplete
- universe-the-information-1：catalog_incomplete
- universe-the-information-2：catalog_incomplete
- universe-threads-1：catalog_incomplete
- universe-threads-2：catalog_incomplete
- universe-tiktok-1：catalog_incomplete
- universe-tiktok-2：catalog_incomplete
- universe-tldr-ai-1：catalog_incomplete
- universe-tldr-ai-2：catalog_incomplete
- universe-washington-post-1：catalog_incomplete
- universe-washington-post-2：catalog_incomplete
- universe-wsj-1：catalog_incomplete
- universe-x-1：catalog_incomplete
- universe-x-2：catalog_incomplete
- universe-youtube-2：catalog_incomplete

## 失败成员
- anthropic-bluesky：degraded（no_content）
- anthropic-newsroom：degraded（catalog_incomplete）
- anthropic-sdk-releases：blocked（missing_credentials）
- anthropic-youtube：blocked（missing_credentials）
- cognitive-revolution-youtube：blocked（missing_credentials）
- cuda-python-releases：blocked（missing_credentials）
- deepmind-blog：degraded（incomplete_fields）
- deepseek-v3-releases：blocked（missing_credentials）
- gdelt-ai：failed（rate_limited）
- gemini-cli-releases：blocked（missing_credentials）
- google-deepmind-youtube：blocked（missing_credentials）
- huggingface-blog：degraded（incomplete_fields）
- huggingface-youtube：blocked（missing_credentials）
- latent-space-youtube：blocked（missing_credentials）
- microsoft-research：failed（internal_error）
- mistral-common-releases：blocked（missing_credentials）
- no-priors-youtube：blocked（missing_credentials）
- nvidia-developer-youtube：blocked（missing_credentials）
- openai-python-releases：blocked（missing_credentials）
- openai-youtube：blocked（missing_credentials）
- reddit-artificial：blocked（missing_credentials）
- reddit-localllama：blocked（missing_credentials）
- reddit-machinelearning：blocked（missing_credentials）
- sec-nvidia-filings：blocked（requires_approval）
- transformers-releases：blocked（missing_credentials）
- universe-ap-1：degraded（catalog_incomplete）
- universe-axios-1：degraded（catalog_incomplete）
- universe-axios-2：degraded（catalog_incomplete）
- universe-bens-bites-1：degraded（catalog_incomplete）
- universe-bens-bites-2：degraded（catalog_incomplete）
- universe-bloomberg-1：degraded（catalog_incomplete）
- universe-brave-search-1：degraded（catalog_incomplete）
- universe-brave-search-2：degraded（catalog_incomplete）
- universe-cognitive-revolution-1：degraded（catalog_incomplete）
- universe-cognitive-revolution-2：degraded（catalog_incomplete）
- universe-discord-1：degraded（catalog_incomplete）
- universe-discord-2：degraded（catalog_incomplete）
- universe-event-registry-1：degraded（catalog_incomplete）
- universe-event-registry-2：degraded（catalog_incomplete）
- universe-facebook-1：degraded（catalog_incomplete）
- universe-facebook-2：degraded（catalog_incomplete）
- universe-financial-times-1：degraded（catalog_incomplete）
- universe-forbes-1：degraded（catalog_incomplete）
- universe-forbes-2：degraded（catalog_incomplete）
- universe-fortune-1：degraded（catalog_incomplete）
- universe-fortune-2：degraded（catalog_incomplete）
- universe-gnews-1：degraded（catalog_incomplete）
- universe-gnews-2：degraded（catalog_incomplete）
- universe-google-trends-1：degraded（catalog_incomplete）
- universe-google-trends-2：degraded（catalog_incomplete）
- universe-instagram-1：degraded（catalog_incomplete）
- universe-instagram-2：degraded（catalog_incomplete）
- universe-linkedin-1：degraded（catalog_incomplete）
- universe-linkedin-2：degraded（catalog_incomplete）
- universe-mediacloud-1：degraded（catalog_incomplete）
- universe-mediacloud-2：degraded（catalog_incomplete）
- universe-newsapi-1：degraded（catalog_incomplete）
- universe-newsapi-2：degraded（catalog_incomplete）
- universe-no-priors-1：degraded（catalog_incomplete）
- universe-no-priors-2：degraded（catalog_incomplete）
- universe-nytimes-1：degraded（catalog_incomplete）
- universe-nytimes-2：degraded（catalog_incomplete）
- universe-producthunt-1：degraded（catalog_incomplete）
- universe-producthunt-2：degraded（catalog_incomplete）
- universe-reddit-1：degraded（catalog_incomplete）
- universe-reddit-2：degraded（catalog_incomplete）
- universe-reuters-1：degraded（catalog_incomplete）
- universe-semafor-1：degraded（catalog_incomplete）
- universe-semafor-2：degraded（catalog_incomplete）
- universe-telegram-1：degraded（catalog_incomplete）
- universe-telegram-2：degraded（catalog_incomplete）
- universe-the-information-1：degraded（catalog_incomplete）
- universe-the-information-2：degraded（catalog_incomplete）
- universe-threads-1：degraded（catalog_incomplete）
- universe-threads-2：degraded（catalog_incomplete）
- universe-tiktok-1：degraded（catalog_incomplete）
- universe-tiktok-2：degraded（catalog_incomplete）
- universe-tldr-ai-1：degraded（catalog_incomplete）
- universe-tldr-ai-2：degraded（catalog_incomplete）
- universe-washington-post-1：degraded（catalog_incomplete）
- universe-washington-post-2：degraded（catalog_incomplete）
- universe-wsj-1：degraded（catalog_incomplete）
- universe-x-1：degraded（catalog_incomplete）
- universe-x-2：degraded（catalog_incomplete）
- universe-youtube-2：degraded（catalog_incomplete）

## 安全边界声明
- 本报告仅汇总冻结批次的通道、状态和结果码，不输出密钥、鉴权头、会话信息、环境变量配置值或响应头。
- 内容抓取只由 Worker 执行；本报告命令不发起网络请求。
