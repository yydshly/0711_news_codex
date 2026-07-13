# 来源研究审计报告

## 汇总

| 指标 | 数量 |
| --- | ---: |
| Provider 总数 | 67 |
| 真实 Target | 32 |
| 占位 | 134 |
| 重复 | 0 |
| 退役 | 0 |
| 待研究 | 32 |
| 已验证 | 0 |

## 来源类别统计

| 类别 | 数量 |
| --- | ---: |
| 聚合来源 | 25 |
| 社区 | 6 |
| 第一方 | 24 |
| 专业媒体 | 62 |
| 研究机构 | 19 |
| 社交平台 | 30 |

## 候选方式统计

| 方式 | 数量 |
| --- | ---: |
| HTML | 1 |
| 公开 API | 1 |

## Target 研究明细

### Anthropic Newsroom（`anthropic-newsroom`）

- 状态：待研究
- 用途：Track Anthropic first-party product, research, policy, and company announcements.
- 所需信息：title、canonical_url、published_at、summary
- 风险：No login, cookie, proxy, browser automation, or bypass is permitted. A robots and terms review plus a compliant static-method sample are required before any automation.
- 未完成项：待补充研究

| 决策 | 方式 | 信息 | 样本 | 限制 |
| --- | --- | --- | --- | --- |
| 仅人工 | HTML | title、canonical_url、published_at | 未运行 | Not approved for automated collection; terms and robots review is required.；No JavaScript rendering, login session, cookie, proxy, or bypass may be used. |

### Anthropic Python SDK Releases（`anthropic-sdk-releases`）

- 状态：待研究
- 用途：Collect AI and technology news-discovery and attribution leads for this named Target.
- 所需信息：title、canonical_url、published_at、summary
- 风险：Do not use cookies, login, proxies, or browser bypasses; credentialed, paid, and dynamic access remain research risks.
- 未完成项：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### arXiv cs.AI（`arxiv-cs-ai`）

- 状态：待研究
- 用途：Collect AI and technology news-discovery and attribution leads for this named Target.
- 所需信息：title、canonical_url、published_at、summary
- 风险：Do not use cookies, login, proxies, or browser bypasses; credentialed, paid, and dynamic access remain research risks.
- 未完成项：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### arXiv cs.CL（`arxiv-cs-cl`）

- 状态：待研究
- 用途：Collect AI and technology news-discovery and attribution leads for this named Target.
- 所需信息：title、canonical_url、published_at、summary
- 风险：Do not use cookies, login, proxies, or browser bypasses; credentialed, paid, and dynamic access remain research risks.
- 未完成项：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### arXiv cs.DC（`arxiv-cs-dc`）

- 状态：待研究
- 用途：Collect AI and technology news-discovery and attribution leads for this named Target.
- 所需信息：title、canonical_url、published_at、summary
- 风险：Do not use cookies, login, proxies, or browser bypasses; credentialed, paid, and dynamic access remain research risks.
- 未完成项：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### arXiv cs.LG（`arxiv-cs-lg`）

- 状态：待研究
- 用途：Collect AI and technology news-discovery and attribution leads for this named Target.
- 所需信息：title、canonical_url、published_at、summary
- 风险：Do not use cookies, login, proxies, or browser bypasses; credentialed, paid, and dynamic access remain research risks.
- 未完成项：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### arXiv cs.SE（`arxiv-cs-se`）

- 状态：待研究
- 用途：Collect AI and technology news-discovery and attribution leads for this named Target.
- 所需信息：title、canonical_url、published_at、summary
- 风险：Do not use cookies, login, proxies, or browser bypasses; credentialed, paid, and dynamic access remain research risks.
- 未完成项：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### Bluesky official account feed（`bluesky-bsky`）

- 状态：待研究
- 用途：Collect AI and technology news-discovery and attribution leads for this named Target.
- 所需信息：title、canonical_url、published_at、summary
- 风险：Do not use cookies, login, proxies, or browser bypasses; credentialed, paid, and dynamic access remain research risks.
- 未完成项：待补充研究

### NVIDIA CUDA Python Releases（`cuda-python-releases`）

- 状态：待研究
- 用途：Collect AI and technology news-discovery and attribution leads for this named Target.
- 所需信息：title、canonical_url、published_at、summary
- 风险：Do not use cookies, login, proxies, or browser bypasses; credentialed, paid, and dynamic access remain research risks.
- 未完成项：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### Google DeepMind Blog（`deepmind-blog`）

- 状态：待研究
- 用途：Collect AI and technology news-discovery and attribution leads for this named Target.
- 所需信息：title、canonical_url、published_at、summary
- 风险：Do not use cookies, login, proxies, or browser bypasses; credentialed, paid, and dynamic access remain research risks.
- 未完成项：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### DeepSeek V3 Releases（`deepseek-v3-releases`）

- 状态：待研究
- 用途：Collect AI and technology news-discovery and attribution leads for this named Target.
- 所需信息：title、canonical_url、published_at、summary
- 风险：Do not use cookies, login, proxies, or browser bypasses; credentialed, paid, and dynamic access remain research risks.
- 未完成项：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### GDELT AI Discovery（`gdelt-ai`）

- 状态：待研究
- 用途：Collect AI and technology news-discovery and attribution leads for this named Target.
- 所需信息：title、canonical_url、published_at、summary
- 风险：Do not use cookies, login, proxies, or browser bypasses; credentialed, paid, and dynamic access remain research risks.
- 未完成项：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### Gemini CLI Releases（`gemini-cli-releases`）

- 状态：待研究
- 用途：Collect AI and technology news-discovery and attribution leads for this named Target.
- 所需信息：title、canonical_url、published_at、summary
- 风险：Do not use cookies, login, proxies, or browser bypasses; credentialed, paid, and dynamic access remain research risks.
- 未完成项：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### Google AI Blog（`google-ai-blog`）

- 状态：待研究
- 用途：Collect AI and technology news-discovery and attribution leads for this named Target.
- 所需信息：title、canonical_url、published_at、summary
- 风险：Do not use cookies, login, proxies, or browser bypasses; credentialed, paid, and dynamic access remain research risks.
- 未完成项：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### Google News AI discovery（`google-news-ai`）

- 状态：待研究
- 用途：Collect AI and technology news-discovery and attribution leads for this named Target.
- 所需信息：title、canonical_url、published_at、summary
- 风险：Do not use cookies, login, proxies, or browser bypasses; credentialed, paid, and dynamic access remain research risks.
- 未完成项：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### Hacker News Best Stories（`hackernews-best`）

- 状态：待研究
- 用途：Collect AI and technology news-discovery and attribution leads for this named Target.
- 所需信息：title、canonical_url、published_at、summary
- 风险：Do not use cookies, login, proxies, or browser bypasses; credentialed, paid, and dynamic access remain research risks.
- 未完成项：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### Hacker News New Stories（`hackernews-new`）

- 状态：待研究
- 用途：Collect AI and technology news-discovery and attribution leads for this named Target.
- 所需信息：title、canonical_url、published_at、summary
- 风险：Do not use cookies, login, proxies, or browser bypasses; credentialed, paid, and dynamic access remain research risks.
- 未完成项：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### Hacker News Top Stories（`hackernews-top`）

- 状态：待研究
- 用途：Collect AI and technology news-discovery and attribution leads for this named Target.
- 所需信息：title、canonical_url、published_at、summary
- 风险：Do not use cookies, login, proxies, or browser bypasses; credentialed, paid, and dynamic access remain research risks.
- 未完成项：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### Hugging Face Blog（`huggingface-blog`）

- 状态：待研究
- 用途：Collect AI and technology news-discovery and attribution leads for this named Target.
- 所需信息：title、canonical_url、published_at、summary
- 风险：Do not use cookies, login, proxies, or browser bypasses; credentialed, paid, and dynamic access remain research risks.
- 未完成项：待补充研究

### Mastodon official account statuses（`mastodon-mastodon`）

- 状态：待研究
- 用途：Collect AI and technology news-discovery and attribution leads for this named Target.
- 所需信息：title、canonical_url、published_at、summary
- 风险：Do not use cookies, login, proxies, or browser bypasses; credentialed, paid, and dynamic access remain research risks.
- 未完成项：待补充研究

### Microsoft Research（`microsoft-research`）

- 状态：待研究
- 用途：Collect AI and technology news-discovery and attribution leads for this named Target.
- 所需信息：title、canonical_url、published_at、summary
- 风险：Do not use cookies, login, proxies, or browser bypasses; credentialed, paid, and dynamic access remain research risks.
- 未完成项：待补充研究

### Mistral Common Releases（`mistral-common-releases`）

- 状态：待研究
- 用途：Collect AI and technology news-discovery and attribution leads for this named Target.
- 所需信息：title、canonical_url、published_at、summary
- 风险：Do not use cookies, login, proxies, or browser bypasses; credentialed, paid, and dynamic access remain research risks.
- 未完成项：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### NVIDIA Developer Blog（`nvidia-developer-blog`）

- 状态：待研究
- 用途：Collect AI and technology news-discovery and attribution leads for this named Target.
- 所需信息：title、canonical_url、published_at、summary
- 风险：Do not use cookies, login, proxies, or browser bypasses; credentialed, paid, and dynamic access remain research risks.
- 未完成项：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### OpenAI News（`openai-news`）

- 状态：待研究
- 用途：Collect AI and technology news-discovery and attribution leads for this named Target.
- 所需信息：title、canonical_url、published_at、summary
- 风险：Do not use cookies, login, proxies, or browser bypasses; credentialed, paid, and dynamic access remain research risks.
- 未完成项：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### OpenAI Python SDK Releases（`openai-python-releases`）

- 状态：待研究
- 用途：Collect AI and technology news-discovery and attribution leads for this named Target.
- 所需信息：title、canonical_url、published_at、summary
- 风险：Do not use cookies, login, proxies, or browser bypasses; credentialed, paid, and dynamic access remain research risks.
- 未完成项：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### OpenAI YouTube（`openai-youtube`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：无

### Qwen3 Releases（`qwen3-releases`）

- 状态：待研究
- 用途：Collect AI and technology news-discovery and attribution leads for this named Target.
- 所需信息：title、canonical_url、published_at、summary
- 风险：Do not use cookies, login, proxies, or browser bypasses; credentialed, paid, and dynamic access remain research risks.
- 未完成项：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### Reddit Artificial（`reddit-artificial`）

- 状态：待研究
- 用途：Collect AI and technology news-discovery and attribution leads for this named Target.
- 所需信息：title、canonical_url、published_at、summary
- 风险：Do not use cookies, login, proxies, or browser bypasses; credentialed, paid, and dynamic access remain research risks.
- 未完成项：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### Reddit LocalLLaMA（`reddit-localllama`）

- 状态：待研究
- 用途：Collect AI and technology news-discovery and attribution leads for this named Target.
- 所需信息：title、canonical_url、published_at、summary
- 风险：Do not use cookies, login, proxies, or browser bypasses; credentialed, paid, and dynamic access remain research risks.
- 未完成项：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### Reddit MachineLearning（`reddit-machinelearning`）

- 状态：待研究
- 用途：Collect AI and technology news-discovery and attribution leads for this named Target.
- 所需信息：title、canonical_url、published_at、summary
- 风险：Do not use cookies, login, proxies, or browser bypasses; credentialed, paid, and dynamic access remain research risks.
- 未完成项：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### SEC EDGAR NVIDIA Filings（`sec-nvidia-filings`）

- 状态：待研究
- 用途：Detect NVIDIA regulatory filings relevant to AI infrastructure, results, risk, and material business changes.
- 所需信息：title、canonical_url、published_at、summary
- 风险：Use only documented public API access with a policy-compliant client; do not use cookies, login, proxy rotation, browser bypasses, or unreviewed headers.
- 未完成项：待补充研究

| 决策 | 方式 | 信息 | 样本 | 限制 |
| --- | --- | --- | --- | --- |
| 仅人工 | 公开 API | title、canonical_url、published_at、summary | 未运行 | Requires a source-specific review of SEC programmatic-access requirements before probing or ingestion.；Filing metadata is regulatory context and does not establish editorial news coverage. |

### Techmeme Feed（`techmeme-feed`）

- 状态：待研究
- 用途：Collect AI and technology news-discovery and attribution leads for this named Target.
- 所需信息：title、canonical_url、published_at、summary
- 风险：Do not use cookies, login, proxies, or browser bypasses; credentialed, paid, and dynamic access remain research risks.
- 未完成项：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### Hugging Face Transformers Releases（`transformers-releases`）

- 状态：待研究
- 用途：Collect AI and technology news-discovery and attribution leads for this named Target.
- 所需信息：title、canonical_url、published_at、summary
- 风险：Do not use cookies, login, proxies, or browser bypasses; credentialed, paid, and dynamic access remain research risks.
- 未完成项：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### AI Snake Oil primary（`universe-ai-snake-oil-1`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### AI Snake Oil AI discovery（`universe-ai-snake-oil-2`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### Anthropic primary（`universe-anthropic-1`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### Anthropic AI discovery（`universe-anthropic-2`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### Associated Press primary（`universe-ap-1`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### Associated Press AI discovery（`universe-ap-2`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### Ars Technica primary（`universe-ars-technica-1`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### Ars Technica AI discovery（`universe-ars-technica-2`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### arXiv primary（`universe-arxiv-1`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### arXiv AI discovery（`universe-arxiv-2`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### Axios Technology primary（`universe-axios-1`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### Axios Technology AI discovery（`universe-axios-2`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### BBC Technology primary（`universe-bbc-1`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### BBC Technology AI discovery（`universe-bbc-2`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### Ben's Bites primary（`universe-bens-bites-1`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### Ben's Bites AI discovery（`universe-bens-bites-2`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### Bloomberg Technology primary（`universe-bloomberg-1`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### Bloomberg Technology AI discovery（`universe-bloomberg-2`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### Bluesky primary（`universe-bluesky-1`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### Bluesky AI discovery（`universe-bluesky-2`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### Brave Search API primary（`universe-brave-search-1`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### Brave Search API AI discovery（`universe-brave-search-2`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### CNBC Technology primary（`universe-cnbc-1`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### CNBC Technology AI discovery（`universe-cnbc-2`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### The Cognitive Revolution primary（`universe-cognitive-revolution-1`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### The Cognitive Revolution AI discovery（`universe-cognitive-revolution-2`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### Discord Communities primary（`universe-discord-1`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### Discord Communities AI discovery（`universe-discord-2`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### Event Registry primary（`universe-event-registry-1`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### Event Registry AI discovery（`universe-event-registry-2`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### Facebook Pages primary（`universe-facebook-1`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### Facebook Pages AI discovery（`universe-facebook-2`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### Financial Times Technology primary（`universe-financial-times-1`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### Financial Times Technology AI discovery（`universe-financial-times-2`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### Forbes Innovation primary（`universe-forbes-1`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### Forbes Innovation AI discovery（`universe-forbes-2`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### Fortune Technology primary（`universe-fortune-1`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### Fortune Technology AI discovery（`universe-fortune-2`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### GDELT primary（`universe-gdelt-1`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### GDELT AI discovery（`universe-gdelt-2`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### GitHub primary（`universe-github-1`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### GitHub AI discovery（`universe-github-2`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### GNews API primary（`universe-gnews-1`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### GNews API AI discovery（`universe-gnews-2`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### Google AI primary（`universe-google-ai-1`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### Google AI AI discovery（`universe-google-ai-2`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### Google News primary（`universe-google-news-1`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### Google News AI discovery（`universe-google-news-2`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### Google Trends primary（`universe-google-trends-1`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### Google Trends AI discovery（`universe-google-trends-2`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### The Guardian Technology primary（`universe-guardian-1`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### The Guardian Technology AI discovery（`universe-guardian-2`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### Hacker News primary（`universe-hackernews-1`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### Hacker News AI discovery（`universe-hackernews-2`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### Hard Fork primary（`universe-hard-fork-1`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### Hard Fork AI discovery（`universe-hard-fork-2`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### Hugging Face Daily Papers primary（`universe-huggingface-papers-1`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### Hugging Face Daily Papers AI discovery（`universe-huggingface-papers-2`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### Import AI primary（`universe-import-ai-1`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### Import AI AI discovery（`universe-import-ai-2`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### Instagram primary（`universe-instagram-1`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### Instagram AI discovery（`universe-instagram-2`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### Interconnects primary（`universe-interconnects-1`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### Interconnects AI discovery（`universe-interconnects-2`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### Latent Space primary（`universe-latent-space-1`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### Latent Space AI discovery（`universe-latent-space-2`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### LinkedIn primary（`universe-linkedin-1`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### LinkedIn AI discovery（`universe-linkedin-2`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### Mastodon primary（`universe-mastodon-1`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### Mastodon AI discovery（`universe-mastodon-2`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### Media Cloud primary（`universe-mediacloud-1`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### Media Cloud AI discovery（`universe-mediacloud-2`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### MIT Technology Review primary（`universe-mit-tech-review-1`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### MIT Technology Review AI discovery（`universe-mit-tech-review-2`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### NewsAPI primary（`universe-newsapi-1`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### NewsAPI AI discovery（`universe-newsapi-2`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### No Priors primary（`universe-no-priors-1`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。

### No Priors AI discovery（`universe-no-priors-2`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。

### npm Registry primary（`universe-npm-1`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### npm Registry AI discovery（`universe-npm-2`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### NVIDIA primary（`universe-nvidia-1`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### NVIDIA AI discovery（`universe-nvidia-2`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### The New York Times Technology primary（`universe-nytimes-1`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### The New York Times Technology AI discovery（`universe-nytimes-2`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### OpenAI primary（`universe-openai-1`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### OpenAI AI discovery（`universe-openai-2`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### OpenReview primary（`universe-openreview-1`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### OpenReview AI discovery（`universe-openreview-2`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### Polymarket primary（`universe-polymarket-1`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### Polymarket AI discovery（`universe-polymarket-2`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### Product Hunt primary（`universe-producthunt-1`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### Product Hunt AI discovery（`universe-producthunt-2`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### PyPI primary（`universe-pypi-1`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### PyPI AI discovery（`universe-pypi-2`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### Reddit primary（`universe-reddit-1`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### Reddit AI discovery（`universe-reddit-2`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### Reuters primary（`universe-reuters-1`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### Reuters AI discovery（`universe-reuters-2`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### SEC EDGAR primary（`universe-sec-edgar-1`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### SEC EDGAR AI discovery（`universe-sec-edgar-2`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### Semafor Technology primary（`universe-semafor-1`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### Semafor Technology AI discovery（`universe-semafor-2`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### Semantic Scholar primary（`universe-semantic-scholar-1`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### Semantic Scholar AI discovery（`universe-semantic-scholar-2`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### TechCrunch primary（`universe-techcrunch-1`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### TechCrunch AI discovery（`universe-techcrunch-2`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### Techmeme primary（`universe-techmeme-1`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### Techmeme AI discovery（`universe-techmeme-2`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### Telegram Public Channels primary（`universe-telegram-1`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### Telegram Public Channels AI discovery（`universe-telegram-2`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### The Batch primary（`universe-the-batch-1`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### The Batch AI discovery（`universe-the-batch-2`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### The Information primary（`universe-the-information-1`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### The Information AI discovery（`universe-the-information-2`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### The Verge primary（`universe-the-verge-1`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### The Verge AI discovery（`universe-the-verge-2`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### Threads primary（`universe-threads-1`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### Threads AI discovery（`universe-threads-2`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### TikTok primary（`universe-tiktok-1`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### TikTok AI discovery（`universe-tiktok-2`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### TLDR AI primary（`universe-tldr-ai-1`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### TLDR AI AI discovery（`universe-tldr-ai-2`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### VentureBeat primary（`universe-venturebeat-1`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### VentureBeat AI discovery（`universe-venturebeat-2`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### The Washington Post Technology primary（`universe-washington-post-1`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### The Washington Post Technology AI discovery（`universe-washington-post-2`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### WIRED primary（`universe-wired-1`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### WIRED AI discovery（`universe-wired-2`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### The Wall Street Journal Technology primary（`universe-wsj-1`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### The Wall Street Journal Technology AI discovery（`universe-wsj-2`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### X primary（`universe-x-1`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### X AI discovery（`universe-x-2`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。；同一 Provider 下存在相同 official_identity_url 的重复候选 Target。

### YouTube AI discovery（`universe-youtube-2`）

- 状态：占位
- 用途：未填写
- 所需信息：未填写
- 风险：未填写
- 未完成项：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。；Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。

## 审计发现

- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（gdelt-ai）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（google-news-ai）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（techmeme-feed）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（hackernews-best）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（hackernews-new）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（hackernews-top）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（reddit-artificial）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（reddit-localllama）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（reddit-machinelearning）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（anthropic-sdk-releases）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（cuda-python-releases）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（deepseek-v3-releases）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（gemini-cli-releases）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（mistral-common-releases）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（openai-python-releases）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（qwen3-releases）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（transformers-releases）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（deepmind-blog）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（google-ai-blog）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（nvidia-developer-blog）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（openai-news）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（arxiv-cs-ai）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（arxiv-cs-cl）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（arxiv-cs-dc）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（arxiv-cs-lg）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（arxiv-cs-se）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-ai-snake-oil-1）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-ai-snake-oil-1）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-ai-snake-oil-2）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-ai-snake-oil-2）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-anthropic-1）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-anthropic-1）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-anthropic-2）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-anthropic-2）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-ap-1）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-ap-1）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-ap-2）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-ap-2）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-ars-technica-1）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-ars-technica-1）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-ars-technica-2）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-ars-technica-2）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-arxiv-1）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-arxiv-1）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-arxiv-2）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-arxiv-2）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-axios-1）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-axios-1）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-axios-2）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-axios-2）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-bbc-1）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-bbc-1）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-bbc-2）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-bbc-2）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-bens-bites-1）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-bens-bites-1）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-bens-bites-2）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-bens-bites-2）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-bloomberg-1）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-bloomberg-1）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-bloomberg-2）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-bloomberg-2）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-bluesky-1）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-bluesky-1）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-bluesky-2）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-bluesky-2）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-brave-search-1）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-brave-search-1）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-brave-search-2）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-brave-search-2）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-cnbc-1）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-cnbc-1）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-cnbc-2）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-cnbc-2）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-cognitive-revolution-1）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-cognitive-revolution-1）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-cognitive-revolution-2）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-cognitive-revolution-2）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-discord-1）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-discord-1）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-discord-2）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-discord-2）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-event-registry-1）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-event-registry-1）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-event-registry-2）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-event-registry-2）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-facebook-1）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-facebook-1）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-facebook-2）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-facebook-2）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-financial-times-1）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-financial-times-1）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-financial-times-2）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-financial-times-2）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-forbes-1）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-forbes-1）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-forbes-2）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-forbes-2）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-fortune-1）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-fortune-1）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-fortune-2）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-fortune-2）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-gdelt-1）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-gdelt-1）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-gdelt-2）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-gdelt-2）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-github-1）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-github-1）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-github-2）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-github-2）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-gnews-1）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-gnews-1）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-gnews-2）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-gnews-2）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-google-ai-1）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-google-ai-1）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-google-ai-2）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-google-ai-2）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-google-news-1）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-google-news-1）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-google-news-2）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-google-news-2）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-google-trends-1）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-google-trends-1）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-google-trends-2）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-google-trends-2）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-guardian-1）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-guardian-1）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-guardian-2）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-guardian-2）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-hackernews-1）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-hackernews-1）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-hackernews-2）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-hackernews-2）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-hard-fork-1）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-hard-fork-1）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-hard-fork-2）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-hard-fork-2）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-huggingface-papers-1）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-huggingface-papers-1）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-huggingface-papers-2）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-huggingface-papers-2）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-import-ai-1）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-import-ai-1）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-import-ai-2）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-import-ai-2）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-instagram-1）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-instagram-1）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-instagram-2）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-instagram-2）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-interconnects-1）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-interconnects-1）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-interconnects-2）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-interconnects-2）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-latent-space-1）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-latent-space-1）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-latent-space-2）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-latent-space-2）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-linkedin-1）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-linkedin-1）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-linkedin-2）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-linkedin-2）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-mastodon-1）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-mastodon-1）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-mastodon-2）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-mastodon-2）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-mediacloud-1）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-mediacloud-1）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-mediacloud-2）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-mediacloud-2）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-mit-tech-review-1）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-mit-tech-review-1）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-mit-tech-review-2）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-mit-tech-review-2）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-newsapi-1）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-newsapi-1）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-newsapi-2）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-newsapi-2）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-no-priors-1）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-no-priors-2）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-no-priors-2）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-npm-1）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-npm-1）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-npm-2）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-npm-2）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-nvidia-1）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-nvidia-1）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-nvidia-2）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-nvidia-2）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-nytimes-1）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-nytimes-1）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-nytimes-2）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-nytimes-2）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-openai-1）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-openai-1）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-openai-2）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-openai-2）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-openreview-1）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-openreview-1）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-openreview-2）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-openreview-2）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-polymarket-1）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-polymarket-1）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-polymarket-2）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-polymarket-2）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-producthunt-1）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-producthunt-1）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-producthunt-2）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-producthunt-2）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-pypi-1）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-pypi-1）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-pypi-2）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-pypi-2）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-reddit-1）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-reddit-1）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-reddit-2）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-reddit-2）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-reuters-1）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-reuters-1）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-reuters-2）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-reuters-2）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-sec-edgar-1）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-sec-edgar-1）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-sec-edgar-2）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-sec-edgar-2）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-semafor-1）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-semafor-1）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-semafor-2）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-semafor-2）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-semantic-scholar-1）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-semantic-scholar-1）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-semantic-scholar-2）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-semantic-scholar-2）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-techcrunch-1）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-techcrunch-1）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-techcrunch-2）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-techcrunch-2）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-techmeme-1）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-techmeme-1）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-techmeme-2）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-techmeme-2）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-telegram-1）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-telegram-1）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-telegram-2）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-telegram-2）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-the-batch-1）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-the-batch-1）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-the-batch-2）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-the-batch-2）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-the-information-1）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-the-information-1）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-the-information-2）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-the-information-2）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-the-verge-1）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-the-verge-1）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-the-verge-2）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-the-verge-2）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-threads-1）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-threads-1）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-threads-2）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-threads-2）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-tiktok-1）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-tiktok-1）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-tiktok-2）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-tiktok-2）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-tldr-ai-1）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-tldr-ai-1）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-tldr-ai-2）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-tldr-ai-2）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-venturebeat-1）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-venturebeat-1）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-venturebeat-2）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-venturebeat-2）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-washington-post-1）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-washington-post-1）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-washington-post-2）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-washington-post-2）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-wired-1）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-wired-1）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-wired-2）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-wired-2）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-wsj-1）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-wsj-1）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-wsj-2）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-wsj-2）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-x-1）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-x-1）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-x-2）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-x-2）
- [警告] `placeholder_target`：universe-*-1/2 命名仅提示可能的占位 Target，未自动改变研究状态。（universe-youtube-2）
- [警告] `generic_platform_target`：Target URL 与 Provider 首页相同，可能只是通用平台页而非具体目标。（universe-youtube-2）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（gdelt-ai）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-gdelt-1）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-gdelt-2）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（google-news-ai）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-google-news-1）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-google-news-2）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（techmeme-feed）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-techmeme-1）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-techmeme-2）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（hackernews-best）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（hackernews-new）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（hackernews-top）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-hackernews-1）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-hackernews-2）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（reddit-artificial）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（reddit-localllama）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（reddit-machinelearning）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-reddit-1）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-reddit-2）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（anthropic-sdk-releases）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（cuda-python-releases）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（deepseek-v3-releases）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（gemini-cli-releases）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（mistral-common-releases）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（openai-python-releases）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（qwen3-releases）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（transformers-releases）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-github-1）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-github-2）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（deepmind-blog）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（google-ai-blog）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-google-ai-1）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-google-ai-2）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（nvidia-developer-blog）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-nvidia-1）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-nvidia-2）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（openai-news）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-openai-1）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-openai-2）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（arxiv-cs-ai）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（arxiv-cs-cl）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（arxiv-cs-dc）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（arxiv-cs-lg）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（arxiv-cs-se）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-arxiv-1）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-arxiv-2）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-ai-snake-oil-1）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-ai-snake-oil-2）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-anthropic-1）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-anthropic-2）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-ap-1）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-ap-2）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-ars-technica-1）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-ars-technica-2）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-axios-1）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-axios-2）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-bbc-1）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-bbc-2）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-bens-bites-1）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-bens-bites-2）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-bloomberg-1）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-bloomberg-2）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-bluesky-1）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-bluesky-2）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-brave-search-1）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-brave-search-2）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-cnbc-1）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-cnbc-2）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-cognitive-revolution-1）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-cognitive-revolution-2）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-discord-1）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-discord-2）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-event-registry-1）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-event-registry-2）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-facebook-1）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-facebook-2）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-financial-times-1）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-financial-times-2）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-forbes-1）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-forbes-2）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-fortune-1）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-fortune-2）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-gnews-1）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-gnews-2）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-google-trends-1）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-google-trends-2）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-guardian-1）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-guardian-2）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-hard-fork-1）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-hard-fork-2）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-huggingface-papers-1）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-huggingface-papers-2）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-import-ai-1）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-import-ai-2）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-instagram-1）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-instagram-2）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-interconnects-1）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-interconnects-2）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-latent-space-1）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-latent-space-2）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-linkedin-1）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-linkedin-2）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-mastodon-1）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-mastodon-2）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-mediacloud-1）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-mediacloud-2）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-mit-tech-review-1）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-mit-tech-review-2）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-newsapi-1）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-newsapi-2）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-npm-1）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-npm-2）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-nytimes-1）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-nytimes-2）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-openreview-1）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-openreview-2）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-polymarket-1）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-polymarket-2）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-producthunt-1）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-producthunt-2）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-pypi-1）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-pypi-2）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-reuters-1）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-reuters-2）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-sec-edgar-1）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-sec-edgar-2）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-semafor-1）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-semafor-2）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-semantic-scholar-1）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-semantic-scholar-2）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-techcrunch-1）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-techcrunch-2）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-telegram-1）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-telegram-2）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-the-batch-1）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-the-batch-2）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-the-information-1）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-the-information-2）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-the-verge-1）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-the-verge-2）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-threads-1）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-threads-2）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-tiktok-1）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-tiktok-2）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-tldr-ai-1）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-tldr-ai-2）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-venturebeat-1）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-venturebeat-2）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-washington-post-1）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-washington-post-2）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-wired-1）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-wired-2）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-wsj-1）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-wsj-2）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-x-1）
- [警告] `duplicate_candidate`：同一 Provider 下存在相同 official_identity_url 的重复候选 Target。（universe-x-2）
- [提示] `research_incomplete`：该 Target 尚待完成研究，不计入已验证覆盖。（gdelt-ai）
- [提示] `research_incomplete`：该 Target 尚待完成研究，不计入已验证覆盖。（google-news-ai）
- [提示] `research_incomplete`：该 Target 尚待完成研究，不计入已验证覆盖。（techmeme-feed）
- [提示] `research_incomplete`：该 Target 尚待完成研究，不计入已验证覆盖。（bluesky-bsky）
- [提示] `research_incomplete`：该 Target 尚待完成研究，不计入已验证覆盖。（hackernews-best）
- [提示] `research_incomplete`：该 Target 尚待完成研究，不计入已验证覆盖。（hackernews-new）
- [提示] `research_incomplete`：该 Target 尚待完成研究，不计入已验证覆盖。（hackernews-top）
- [提示] `research_incomplete`：该 Target 尚待完成研究，不计入已验证覆盖。（mastodon-mastodon）
- [提示] `research_incomplete`：该 Target 尚待完成研究，不计入已验证覆盖。（reddit-artificial）
- [提示] `research_incomplete`：该 Target 尚待完成研究，不计入已验证覆盖。（reddit-localllama）
- [提示] `research_incomplete`：该 Target 尚待完成研究，不计入已验证覆盖。（reddit-machinelearning）
- [提示] `research_incomplete`：该 Target 尚待完成研究，不计入已验证覆盖。（anthropic-sdk-releases）
- [提示] `research_incomplete`：该 Target 尚待完成研究，不计入已验证覆盖。（cuda-python-releases）
- [提示] `research_incomplete`：该 Target 尚待完成研究，不计入已验证覆盖。（deepseek-v3-releases）
- [提示] `research_incomplete`：该 Target 尚待完成研究，不计入已验证覆盖。（gemini-cli-releases）
- [提示] `research_incomplete`：该 Target 尚待完成研究，不计入已验证覆盖。（mistral-common-releases）
- [提示] `research_incomplete`：该 Target 尚待完成研究，不计入已验证覆盖。（openai-python-releases）
- [提示] `research_incomplete`：该 Target 尚待完成研究，不计入已验证覆盖。（qwen3-releases）
- [提示] `research_incomplete`：该 Target 尚待完成研究，不计入已验证覆盖。（transformers-releases）
- [提示] `research_incomplete`：该 Target 尚待完成研究，不计入已验证覆盖。（anthropic-newsroom）
- [提示] `research_incomplete`：该 Target 尚待完成研究，不计入已验证覆盖。（deepmind-blog）
- [提示] `research_incomplete`：该 Target 尚待完成研究，不计入已验证覆盖。（google-ai-blog）
- [提示] `research_incomplete`：该 Target 尚待完成研究，不计入已验证覆盖。（huggingface-blog）
- [提示] `research_incomplete`：该 Target 尚待完成研究，不计入已验证覆盖。（microsoft-research）
- [提示] `research_incomplete`：该 Target 尚待完成研究，不计入已验证覆盖。（nvidia-developer-blog）
- [提示] `research_incomplete`：该 Target 尚待完成研究，不计入已验证覆盖。（openai-news）
- [提示] `research_incomplete`：该 Target 尚待完成研究，不计入已验证覆盖。（sec-nvidia-filings）
- [提示] `research_incomplete`：该 Target 尚待完成研究，不计入已验证覆盖。（arxiv-cs-ai）
- [提示] `research_incomplete`：该 Target 尚待完成研究，不计入已验证覆盖。（arxiv-cs-cl）
- [提示] `research_incomplete`：该 Target 尚待完成研究，不计入已验证覆盖。（arxiv-cs-dc）
- [提示] `research_incomplete`：该 Target 尚待完成研究，不计入已验证覆盖。（arxiv-cs-lg）
- [提示] `research_incomplete`：该 Target 尚待完成研究，不计入已验证覆盖。（arxiv-cs-se）
