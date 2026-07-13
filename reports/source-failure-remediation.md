# 来源失败修复报告

基线时间：2026-07-13T11:47:00+00:00
固定失败 Target 数：27

## 分类汇总

| 分类 | 数量 |
| --- | ---: |
| `authentication_or_policy` | 1 |
| `network_transient` | 26 |

## 固定清单

| 来源 | 原探测 | 分类 | 中文原因 | 原访问地址 | 建议动作 |
| --- | ---: | --- | --- | --- |
| Anthropic Python SDK Releases (`anthropic-sdk-releases`) | 38 | `network_transient` | 本次网络或远端服务暂时不可用。 | https://api.github.com/repos/anthropics/anthropic-sdk-python/releases | 保留证据，后续仅允许低频显式复测。 |
| arXiv cs.AI (`arxiv-cs-ai`) | 54 | `network_transient` | 本次网络或远端服务暂时不可用。 | https://export.arxiv.org/api/query | 保留证据，后续仅允许低频显式复测。 |
| arXiv cs.DC (`arxiv-cs-dc`) | 56 | `network_transient` | 本次网络或远端服务暂时不可用。 | https://export.arxiv.org/api/query | 保留证据，后续仅允许低频显式复测。 |
| arXiv cs.SE (`arxiv-cs-se`) | 58 | `network_transient` | 本次网络或远端服务暂时不可用。 | https://export.arxiv.org/api/query | 保留证据，后续仅允许低频显式复测。 |
| Bluesky official account feed (`bluesky-bsky`) | 30 | `network_transient` | 本次网络或远端服务暂时不可用。 | https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed | 保留证据，后续仅允许低频显式复测。 |
| Google DeepMind Blog (`deepmind-blog`) | 47 | `network_transient` | 本次网络或远端服务暂时不可用。 | https://deepmind.google/blog/rss.xml | 保留证据，后续仅允许低频显式复测。 |
| DeepSeek V3 Releases (`deepseek-v3-releases`) | 40 | `network_transient` | 本次网络或远端服务暂时不可用。 | https://api.github.com/repos/deepseek-ai/DeepSeek-V3/releases | 保留证据，后续仅允许低频显式复测。 |
| GDELT AI Discovery (`gdelt-ai`) | 27 | `network_transient` | 本次网络或远端服务暂时不可用。 | https://api.gdeltproject.org/api/v2/doc/doc | 保留证据，后续仅允许低频显式复测。 |
| Google AI Blog (`google-ai-blog`) | 48 | `network_transient` | 本次网络或远端服务暂时不可用。 | https://blog.google/innovation-and-ai/technology/ai/rss/ | 保留证据，后续仅允许低频显式复测。 |
| Google News AI discovery (`google-news-ai`) | 28 | `network_transient` | 本次网络或远端服务暂时不可用。 | https://news.google.com/rss/search | 保留证据，后续仅允许低频显式复测。 |
| Hacker News Best Stories (`hackernews-best`) | 31 | `network_transient` | 本次网络或远端服务暂时不可用。 | https://hacker-news.firebaseio.com/v0/beststories.json | 保留证据，后续仅允许低频显式复测。 |
| Hacker News New Stories (`hackernews-new`) | 32 | `network_transient` | 本次网络或远端服务暂时不可用。 | https://hacker-news.firebaseio.com/v0/newstories.json | 保留证据，后续仅允许低频显式复测。 |
| Hacker News Top Stories (`hackernews-top`) | 33 | `network_transient` | 本次网络或远端服务暂时不可用。 | https://hacker-news.firebaseio.com/v0/topstories.json | 保留证据，后续仅允许低频显式复测。 |
| Hugging Face Blog (`huggingface-blog`) | 49 | `network_transient` | 本次网络或远端服务暂时不可用。 | https://huggingface.co/blog/feed.xml | 保留证据，后续仅允许低频显式复测。 |
| Mastodon official account statuses (`mastodon-mastodon`) | 34 | `network_transient` | 本次网络或远端服务暂时不可用。 | https://mastodon.social/api/v1/accounts/13179/statuses | 保留证据，后续仅允许低频显式复测。 |
| Mistral Common Releases (`mistral-common-releases`) | 42 | `network_transient` | 本次网络或远端服务暂时不可用。 | https://api.github.com/repos/mistralai/mistral-common/releases | 保留证据，后续仅允许低频显式复测。 |
| NVIDIA Developer Blog (`nvidia-developer-blog`) | 51 | `network_transient` | 本次网络或远端服务暂时不可用。 | https://developer.nvidia.com/blog/feed/ | 保留证据，后续仅允许低频显式复测。 |
| OpenAI News (`openai-news`) | 52 | `network_transient` | 本次网络或远端服务暂时不可用。 | https://openai.com/news/rss.xml | 保留证据，后续仅允许低频显式复测。 |
| OpenAI Python SDK Releases (`openai-python-releases`) | 43 | `network_transient` | 本次网络或远端服务暂时不可用。 | https://api.github.com/repos/openai/openai-python/releases | 保留证据，后续仅允许低频显式复测。 |
| OpenAI YouTube (`openai-youtube`) | 191 | `authentication_or_policy` | 来源需要凭据、登录或受平台政策限制。 | https://www.googleapis.com/youtube/v3/videos | 停止自动处理，保留解锁条件或仅发现定位。 |
| Qwen3 Releases (`qwen3-releases`) | 44 | `network_transient` | 本次网络或远端服务暂时不可用。 | https://api.github.com/repos/QwenLM/Qwen3/releases | 保留证据，后续仅允许低频显式复测。 |
| Techmeme Feed (`techmeme-feed`) | 29 | `network_transient` | 本次网络或远端服务暂时不可用。 | https://www.techmeme.com/feed.xml | 保留证据，后续仅允许低频显式复测。 |
| AI Snake Oil primary (`universe-ai-snake-oil-1`) | 59 | `network_transient` | 本次网络或远端服务暂时不可用。 | https://www.aisnakeoil.com/feed | 保留证据，后续仅允许低频显式复测。 |
| Ars Technica primary (`universe-ars-technica-1`) | 65 | `network_transient` | 本次网络或远端服务暂时不可用。 | https://feeds.arstechnica.com/arstechnica/index | 保留证据，后续仅允许低频显式复测。 |
| Latent Space primary (`universe-latent-space-1`) | 123 | `network_transient` | 本次网络或远端服务暂时不可用。 | https://www.latent.space/feed | 保留证据，后续仅允许低频显式复测。 |
| TechCrunch primary (`universe-techcrunch-1`) | 163 | `network_transient` | 本次网络或远端服务暂时不可用。 | https://techcrunch.com/feed/ | 保留证据，后续仅允许低频显式复测。 |
| The Verge primary (`universe-the-verge-1`) | 173 | `network_transient` | 本次网络或远端服务暂时不可用。 | https://www.theverge.com/rss/index.xml | 保留证据，后续仅允许低频显式复测。 |
