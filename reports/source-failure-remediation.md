# 来源失败修复报告

基线时间：2026-07-13T11:47:00+00:00
固定失败 Target 数：27
修复前可试用来源：16
修复后可试用来源：37

## 分类汇总

| 分类 | 数量 |
| --- | ---: |
| `authentication_or_policy` | 1 |
| `network_transient` | 26 |

## 固定清单

| 来源 | 原探测与分类 | 官方候选 | 研究探测 | 内容探测 | 试用与抓取 | HTML | 最终结论 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Anthropic Python SDK Releases (`anthropic-sdk-releases`) | 38 / `network_transient`；本次网络或远端服务暂时不可用。；https://api.github.com/repos/anthropics/anthropic-sdk-python/releases | github-releases-api / public_api | succeeded / 5 条 | success / 5 条 / 100% | 可试用；succeeded；接收 5 / 新增 5 | 不涉及（RSS/API 主路径） | 试用抓取已验证 |
| arXiv cs.AI (`arxiv-cs-ai`) | 54 / `network_transient`；本次网络或远端服务暂时不可用。；https://export.arxiv.org/api/query | arxiv-atom-api / atom | succeeded / 5 条 | success / 5 条 / 100% | 可试用；succeeded；接收 5 / 新增 0 | 不涉及（RSS/API 主路径） | 试用抓取已验证 |
| arXiv cs.DC (`arxiv-cs-dc`) | 56 / `network_transient`；本次网络或远端服务暂时不可用。；https://export.arxiv.org/api/query | arxiv-atom-api / atom | succeeded / 5 条 | success / 5 条 / 100% | 可试用；succeeded；接收 5 / 新增 5 | 不涉及（RSS/API 主路径） | 试用抓取已验证 |
| arXiv cs.SE (`arxiv-cs-se`) | 58 / `network_transient`；本次网络或远端服务暂时不可用。；https://export.arxiv.org/api/query | arxiv-atom-api / atom | succeeded / 5 条 | success / 5 条 / 100% | 可试用；succeeded；接收 5 / 新增 5 | 不涉及（RSS/API 主路径） | 试用抓取已验证 |
| Bluesky official account feed (`bluesky-bsky`) | 30 / `network_transient`；本次网络或远端服务暂时不可用。；https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed | bluesky-author-feed / public_api | succeeded / 0 条 | success / 5 条 / 100% | 可试用；succeeded；接收 5 / 新增 5 | 不涉及（RSS/API 主路径） | 试用抓取已验证 |
| Google DeepMind Blog (`deepmind-blog`) | 47 / `network_transient`；本次网络或远端服务暂时不可用。；https://deepmind.google/blog/rss.xml | official-feed / rss | succeeded / 5 条 | degraded / 5 条 / 85% | 不可试用：不可试用抓取：最新探测未成功。 | 不涉及（RSS/API 主路径） | 暂不试用：不可试用抓取：最新探测未成功。 |
| DeepSeek V3 Releases (`deepseek-v3-releases`) | 40 / `network_transient`；本次网络或远端服务暂时不可用。；https://api.github.com/repos/deepseek-ai/DeepSeek-V3/releases | github-releases-api / public_api | succeeded / 1 条 | success / 1 条 / 100% | 可试用；succeeded；接收 1 / 新增 1 | 不涉及（RSS/API 主路径） | 试用抓取已验证 |
| GDELT AI Discovery (`gdelt-ai`) | 27 / `network_transient`；本次网络或远端服务暂时不可用。；https://api.gdeltproject.org/api/v2/doc/doc | gdelt-doc-api / public_api | blocked / 0 条 | failed / 0 条 / 0% | 不可试用：不可试用抓取：最新探测未成功。 | 不涉及（RSS/API 主路径） | 受限：HTTP 429；停止自动重试，等待复查窗口 |
| Google AI Blog (`google-ai-blog`) | 48 / `network_transient`；本次网络或远端服务暂时不可用。；https://blog.google/innovation-and-ai/technology/ai/rss/ | official-feed / rss | succeeded / 5 条 | success / 5 条 / 100% | 可试用；succeeded；接收 5 / 新增 5 | 不涉及（RSS/API 主路径） | 试用抓取已验证 |
| Google News AI discovery (`google-news-ai`) | 28 / `network_transient`；本次网络或远端服务暂时不可用。；https://news.google.com/rss/search | google-news-search-rss / rss | succeeded / 5 条 | success / 5 条 / 100% | 可试用；succeeded；接收 5 / 新增 4 | 不涉及（RSS/API 主路径） | 试用抓取已验证 |
| Hacker News Best Stories (`hackernews-best`) | 31 / `network_transient`；本次网络或远端服务暂时不可用。；https://hacker-news.firebaseio.com/v0/beststories.json | hackernews-public-api / public_api | succeeded / 0 条 | success / 5 条 / 96% | 可试用；succeeded；接收 5 / 新增 2 | 不涉及（RSS/API 主路径） | 试用抓取已验证 |
| Hacker News New Stories (`hackernews-new`) | 32 / `network_transient`；本次网络或远端服务暂时不可用。；https://hacker-news.firebaseio.com/v0/newstories.json | hackernews-public-api / public_api | succeeded / 0 条 | success / 5 条 / 100% | 可试用；succeeded；接收 5 / 新增 5 | 不涉及（RSS/API 主路径） | 试用抓取已验证 |
| Hacker News Top Stories (`hackernews-top`) | 33 / `network_transient`；本次网络或远端服务暂时不可用。；https://hacker-news.firebaseio.com/v0/topstories.json | hackernews-public-api / public_api | succeeded / 0 条 | success / 5 条 / 100% | 可试用；succeeded；接收 5 / 新增 5 | 不涉及（RSS/API 主路径） | 试用抓取已验证 |
| Hugging Face Blog (`huggingface-blog`) | 49 / `network_transient`；本次网络或远端服务暂时不可用。；https://huggingface.co/blog/feed.xml | official-feed / rss | succeeded / 5 条 | degraded / 5 条 / 75% | 不可试用：不可试用抓取：最新探测未成功。 | 不涉及（RSS/API 主路径） | 暂不试用：不可试用抓取：最新探测未成功。 |
| Mastodon official account statuses (`mastodon-mastodon`) | 34 / `network_transient`；本次网络或远端服务暂时不可用。；https://mastodon.social/api/v1/accounts/13179/statuses | mastodon-account-statuses / public_api | succeeded / 5 条 | degraded / 5 条 / 43% | 不可试用：不可试用抓取：最新探测未成功。 | 不涉及（RSS/API 主路径） | 暂不试用：不可试用抓取：最新探测未成功。 |
| Mistral Common Releases (`mistral-common-releases`) | 42 / `network_transient`；本次网络或远端服务暂时不可用。；https://api.github.com/repos/mistralai/mistral-common/releases | github-releases-api / public_api | succeeded / 5 条 | success / 5 条 / 100% | 可试用；succeeded；接收 5 / 新增 5 | 不涉及（RSS/API 主路径） | 试用抓取已验证 |
| NVIDIA Developer Blog (`nvidia-developer-blog`) | 51 / `network_transient`；本次网络或远端服务暂时不可用。；https://developer.nvidia.com/blog/feed/ | official-feed / atom | succeeded / 5 条 | success / 5 条 / 100% | 可试用；succeeded；接收 5 / 新增 5 | 不涉及（RSS/API 主路径） | 试用抓取已验证 |
| OpenAI News (`openai-news`) | 52 / `network_transient`；本次网络或远端服务暂时不可用。；https://openai.com/news/rss.xml | official-feed / rss | succeeded / 5 条 | success / 5 条 / 100% | 可试用；succeeded；接收 5 / 新增 1 | 不涉及（RSS/API 主路径） | 试用抓取已验证 |
| OpenAI Python SDK Releases (`openai-python-releases`) | 43 / `network_transient`；本次网络或远端服务暂时不可用。；https://api.github.com/repos/openai/openai-python/releases | github-releases-api / public_api | succeeded / 5 条 | success / 5 条 / 100% | 可试用；succeeded；接收 5 / 新增 5 | 不涉及（RSS/API 主路径） | 试用抓取已验证 |
| OpenAI YouTube (`openai-youtube`) | 191 / `authentication_or_policy`；来源需要凭据、登录或受平台政策限制。；https://www.googleapis.com/youtube/v3/videos | youtube-atom / atom | succeeded / 5 条 | degraded / 5 条 / 80% | 不可试用：不可试用抓取：最新探测未成功。 | 不涉及（RSS/API 主路径） | 暂不试用：不可试用抓取：最新探测未成功。 |
| Qwen3 Releases (`qwen3-releases`) | 44 / `network_transient`；本次网络或远端服务暂时不可用。；https://api.github.com/repos/QwenLM/Qwen3/releases | github-releases-api / public_api | succeeded / 0 条 | degraded / 0 条 / 0% | 不可试用：不可试用抓取：最新探测未成功。 | 不涉及（RSS/API 主路径） | 暂不试用：不可试用抓取：最新探测未成功。 |
| Techmeme Feed (`techmeme-feed`) | 29 / `network_transient`；本次网络或远端服务暂时不可用。；https://www.techmeme.com/feed.xml | publisher-feed / rss | succeeded / 5 条 | success / 5 条 / 100% | 可试用；succeeded；接收 5 / 新增 5 | 不涉及（RSS/API 主路径） | 试用抓取已验证 |
| AI Snake Oil primary (`universe-ai-snake-oil-1`) | 59 / `network_transient`；本次网络或远端服务暂时不可用。；https://www.aisnakeoil.com/feed | publisher-feed / rss | succeeded / 5 条 | success / 5 条 / 100% | 可试用；succeeded；接收 5 / 新增 5 | 不涉及（RSS/API 主路径） | 试用抓取已验证 |
| Ars Technica primary (`universe-ars-technica-1`) | 65 / `network_transient`；本次网络或远端服务暂时不可用。；https://feeds.arstechnica.com/arstechnica/index | publisher-feed / rss | succeeded / 5 条 | success / 5 条 / 100% | 可试用；succeeded；接收 5 / 新增 5 | 不涉及（RSS/API 主路径） | 试用抓取已验证 |
| Latent Space primary (`universe-latent-space-1`) | 123 / `network_transient`；本次网络或远端服务暂时不可用。；https://www.latent.space/feed | publisher-feed / rss | succeeded / 5 条 | success / 5 条 / 100% | 可试用；succeeded；接收 5 / 新增 5 | 不涉及（RSS/API 主路径） | 试用抓取已验证 |
| TechCrunch primary (`universe-techcrunch-1`) | 163 / `network_transient`；本次网络或远端服务暂时不可用。；https://techcrunch.com/feed/ | publisher-feed / rss | succeeded / 5 条 | success / 5 条 / 100% | 可试用；succeeded；接收 5 / 新增 4 | 不涉及（RSS/API 主路径） | 试用抓取已验证 |
| The Verge primary (`universe-the-verge-1`) | 173 / `network_transient`；本次网络或远端服务暂时不可用。；https://www.theverge.com/rss/index.xml | publisher-feed / rss | succeeded / 5 条 | success / 5 条 / 100% | 可试用；succeeded；接收 5 / 新增 5 | 不涉及（RSS/API 主路径） | 试用抓取已验证 |
