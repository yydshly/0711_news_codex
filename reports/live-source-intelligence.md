# News Codex Source Intelligence Report

Generated: 2026-07-11T23:32:42.316608+00:00

| Source | Nature | Roles | Primary method | Risk | Status | Probe | Completeness | Reason |
|---|---|---|---|---:|---|---|---:|---|
| Anthropic Python SDK Releases | first_party | discovery, evidence | rest_api | 4 (low) | candidate | success | 100% | Parsed 5 JSON samples; field completeness 100% |
| arXiv cs.AI | research | discovery, evidence | atom | 4 (low) | candidate | success | 100% | Parsed 5 feed samples; field completeness 100% |
| arXiv cs.CL | research | discovery, evidence | atom | 4 (low) | candidate | success | 100% | Parsed 5 feed samples; field completeness 100% |
| arXiv cs.DC | research | discovery, evidence | atom | 4 (low) | candidate | success | 100% | Parsed 5 feed samples; field completeness 100% |
| arXiv cs.LG | research | discovery, evidence | atom | 4 (low) | candidate | success | 100% | Parsed 5 feed samples; field completeness 100% |
| arXiv cs.SE | research | discovery, evidence | atom | 4 (low) | candidate | success | 100% | Parsed 5 feed samples; field completeness 100% |
| DeepSeek V3 Releases | first_party | discovery, evidence | rest_api | 5 (low) | candidate | success | 100% | Parsed 1 JSON samples; field completeness 100% |
| GDELT AI Discovery | aggregator | discovery | public_api | 11 (medium) | candidate | failed | 0% | Request timed out |
| Gemini CLI Releases | first_party | discovery, evidence | rest_api | 4 (low) | candidate | success | 100% | Parsed 5 JSON samples; field completeness 100% |
| Google AI Blog | first_party | discovery, evidence | rss | 3 (low) | candidate | success | 100% | Parsed 5 feed samples; field completeness 100% |
| Google DeepMind Blog | first_party | discovery, evidence | rss | 3 (low) | candidate | degraded | 85% | Parsed 5 feed samples; field completeness 85% |
| Hacker News Best Stories | community | discovery, engagement, context | public_api | 5 (low) | candidate | success | 100% | Parsed 5 JSON samples; field completeness 100% |
| Hacker News New Stories | community | discovery, context | public_api | 5 (low) | candidate | success | 100% | Parsed 5 JSON samples; field completeness 100% |
| Hacker News Top Stories | community | discovery, engagement, context | public_api | 5 (low) | candidate | success | 100% | Parsed 5 JSON samples; field completeness 100% |
| Hugging Face Blog | first_party | discovery, evidence | rss | 3 (low) | candidate | degraded | 75% | Parsed 5 feed samples; field completeness 75% |
| Hugging Face Transformers Releases | first_party | discovery, evidence | rest_api | 4 (low) | candidate | success | 100% | Parsed 5 JSON samples; field completeness 100% |
| Microsoft Research | first_party | discovery, evidence | rss | 3 (low) | candidate | success | 100% | Parsed 5 feed samples; field completeness 100% |
| Mistral Common Releases | first_party | discovery, evidence | rest_api | 4 (low) | candidate | success | 100% | Parsed 5 JSON samples; field completeness 100% |
| NVIDIA CUDA Python Releases | first_party | discovery, evidence | rest_api | 4 (low) | candidate | success | 100% | Parsed 5 JSON samples; field completeness 100% |
| NVIDIA Developer Blog | first_party | discovery, evidence | atom | 3 (low) | candidate | success | 100% | Parsed 5 feed samples; field completeness 100% |
| OpenAI News | first_party | discovery, evidence | rss | 3 (low) | candidate | success | 100% | Parsed 5 feed samples; field completeness 100% |
| OpenAI Python SDK Releases | first_party | discovery, evidence | rest_api | 4 (low) | candidate | success | 100% | Parsed 5 JSON samples; field completeness 100% |
| Qwen3 Releases | first_party | discovery, evidence | rest_api | 5 (low) | candidate | degraded | 0% | Parsed 0 JSON samples; field completeness 0% |
| Reddit Artificial | community | discovery, engagement, context | rest_api | 12 (medium) | candidate | blocked | 0% | REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET are required for official OAuth access |
| Reddit LocalLLaMA | community | discovery, engagement, context | rest_api | 12 (medium) | candidate | blocked | 0% | REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET are required for official OAuth access |
| Reddit MachineLearning | community | discovery, engagement, context | rest_api | 12 (medium) | candidate | blocked | 0% | REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET are required for official OAuth access |
| Techmeme Feed | aggregator | discovery | rss | 9 (medium) | candidate | success | 100% | Parsed 5 feed samples; field completeness 100% |

## Source details

### Anthropic Python SDK Releases (`anthropic-sdk-releases`)

- Nature: `first_party`
- Roles: `discovery`, `evidence`
- Primary access: `rest_api` - https://api.github.com/repos/anthropics/anthropic-sdk-python/releases
- Fallback access: none documented
- Expected fields: author, canonical_url, published_at, summary, title
- Observed missing fields: none
- Probe: `success`; Parsed 5 JSON samples; field completeness 100%
- Risk breakdown: terms=1, authentication=1, stability=1, data_quality=1, operating_cost=0; total=4 (`low`)
- Recommendation: Low risk; eligible after probe acceptance
- Notes: No additional notes.

### arXiv cs.AI (`arxiv-cs-ai`)

- Nature: `research`
- Roles: `discovery`, `evidence`
- Primary access: `atom` - https://export.arxiv.org/api/query?search_query=cat:cs.AI&sortBy=submittedDate&sortOrder=descending&max_results=5
- Fallback access: none documented
- Expected fields: author, canonical_url, published_at, summary, title
- Observed missing fields: none
- Probe: `success`; Parsed 5 feed samples; field completeness 100%
- Risk breakdown: terms=1, authentication=0, stability=1, data_quality=2, operating_cost=0; total=4 (`low`)
- Recommendation: Low risk; eligible after probe acceptance
- Notes: No additional notes.

### arXiv cs.CL (`arxiv-cs-cl`)

- Nature: `research`
- Roles: `discovery`, `evidence`
- Primary access: `atom` - https://export.arxiv.org/api/query?search_query=cat:cs.CL&sortBy=submittedDate&sortOrder=descending&max_results=5
- Fallback access: none documented
- Expected fields: author, canonical_url, published_at, summary, title
- Observed missing fields: none
- Probe: `success`; Parsed 5 feed samples; field completeness 100%
- Risk breakdown: terms=1, authentication=0, stability=1, data_quality=2, operating_cost=0; total=4 (`low`)
- Recommendation: Low risk; eligible after probe acceptance
- Notes: No additional notes.

### arXiv cs.DC (`arxiv-cs-dc`)

- Nature: `research`
- Roles: `discovery`, `evidence`
- Primary access: `atom` - https://export.arxiv.org/api/query?search_query=cat:cs.DC&sortBy=submittedDate&sortOrder=descending&max_results=5
- Fallback access: none documented
- Expected fields: author, canonical_url, published_at, summary, title
- Observed missing fields: none
- Probe: `success`; Parsed 5 feed samples; field completeness 100%
- Risk breakdown: terms=1, authentication=0, stability=1, data_quality=2, operating_cost=0; total=4 (`low`)
- Recommendation: Low risk; eligible after probe acceptance
- Notes: No additional notes.

### arXiv cs.LG (`arxiv-cs-lg`)

- Nature: `research`
- Roles: `discovery`, `evidence`
- Primary access: `atom` - https://export.arxiv.org/api/query?search_query=cat:cs.LG&sortBy=submittedDate&sortOrder=descending&max_results=5
- Fallback access: none documented
- Expected fields: author, canonical_url, published_at, summary, title
- Observed missing fields: none
- Probe: `success`; Parsed 5 feed samples; field completeness 100%
- Risk breakdown: terms=1, authentication=0, stability=1, data_quality=2, operating_cost=0; total=4 (`low`)
- Recommendation: Low risk; eligible after probe acceptance
- Notes: No additional notes.

### arXiv cs.SE (`arxiv-cs-se`)

- Nature: `research`
- Roles: `discovery`, `evidence`
- Primary access: `atom` - https://export.arxiv.org/api/query?search_query=cat:cs.SE&sortBy=submittedDate&sortOrder=descending&max_results=5
- Fallback access: none documented
- Expected fields: author, canonical_url, published_at, summary, title
- Observed missing fields: none
- Probe: `success`; Parsed 5 feed samples; field completeness 100%
- Risk breakdown: terms=1, authentication=0, stability=1, data_quality=2, operating_cost=0; total=4 (`low`)
- Recommendation: Low risk; eligible after probe acceptance
- Notes: No additional notes.

### DeepSeek V3 Releases (`deepseek-v3-releases`)

- Nature: `first_party`
- Roles: `discovery`, `evidence`
- Primary access: `rest_api` - https://api.github.com/repos/deepseek-ai/DeepSeek-V3/releases
- Fallback access: none documented
- Expected fields: author, canonical_url, published_at, summary, title
- Observed missing fields: none
- Probe: `success`; Parsed 1 JSON samples; field completeness 100%
- Risk breakdown: terms=1, authentication=1, stability=1, data_quality=2, operating_cost=0; total=5 (`low`)
- Recommendation: Low risk; eligible after probe acceptance
- Notes: No additional notes.

### GDELT AI Discovery (`gdelt-ai`)

- Nature: `aggregator`
- Roles: `discovery`
- Primary access: `public_api` - https://api.gdeltproject.org/api/v2/doc/doc
- Fallback access: none documented
- Expected fields: canonical_url, published_at, title
- Observed missing fields: canonical_url, published_at, title
- Probe: `failed`; Request timed out
- Risk breakdown: terms=2, authentication=0, stability=3, data_quality=5, operating_cost=1; total=11 (`medium`)
- Recommendation: Medium risk; fallback method required
- Notes: Discovery only; every item must be resolved to its original publisher before use as evidence.

### Gemini CLI Releases (`gemini-cli-releases`)

- Nature: `first_party`
- Roles: `discovery`, `evidence`
- Primary access: `rest_api` - https://api.github.com/repos/google-gemini/gemini-cli/releases
- Fallback access: none documented
- Expected fields: author, canonical_url, published_at, summary, title
- Observed missing fields: none
- Probe: `success`; Parsed 5 JSON samples; field completeness 100%
- Risk breakdown: terms=1, authentication=1, stability=1, data_quality=1, operating_cost=0; total=4 (`low`)
- Recommendation: Low risk; eligible after probe acceptance
- Notes: No additional notes.

### Google AI Blog (`google-ai-blog`)

- Nature: `first_party`
- Roles: `discovery`, `evidence`
- Primary access: `rss` - https://blog.google/innovation-and-ai/technology/ai/rss/
- Fallback access: none documented
- Expected fields: canonical_url, published_at, summary, title
- Observed missing fields: none
- Probe: `success`; Parsed 5 feed samples; field completeness 100%
- Risk breakdown: terms=1, authentication=0, stability=1, data_quality=1, operating_cost=0; total=3 (`low`)
- Recommendation: Low risk; eligible after probe acceptance
- Notes: No additional notes.

### Google DeepMind Blog (`deepmind-blog`)

- Nature: `first_party`
- Roles: `discovery`, `evidence`
- Primary access: `rss` - https://deepmind.google/blog/rss.xml
- Fallback access: none documented
- Expected fields: canonical_url, published_at, summary, title
- Observed missing fields: summary
- Probe: `degraded`; Parsed 5 feed samples; field completeness 85%
- Risk breakdown: terms=1, authentication=0, stability=1, data_quality=1, operating_cost=0; total=3 (`low`)
- Recommendation: Low risk; eligible after probe acceptance
- Notes: No additional notes.

### Hacker News Best Stories (`hackernews-best`)

- Nature: `community`
- Roles: `discovery`, `engagement`, `context`
- Primary access: `public_api` - https://hacker-news.firebaseio.com/v0/beststories.json
- Fallback access: none documented
- Expected fields: author, canonical_url, engagement, published_at, title
- Observed missing fields: none
- Probe: `success`; Parsed 5 JSON samples; field completeness 100%
- Risk breakdown: terms=1, authentication=0, stability=1, data_quality=3, operating_cost=0; total=5 (`low`)
- Recommendation: Low risk; eligible after probe acceptance
- Notes: No additional notes.

### Hacker News New Stories (`hackernews-new`)

- Nature: `community`
- Roles: `discovery`, `context`
- Primary access: `public_api` - https://hacker-news.firebaseio.com/v0/newstories.json
- Fallback access: none documented
- Expected fields: author, canonical_url, engagement, published_at, title
- Observed missing fields: none
- Probe: `success`; Parsed 5 JSON samples; field completeness 100%
- Risk breakdown: terms=1, authentication=0, stability=1, data_quality=3, operating_cost=0; total=5 (`low`)
- Recommendation: Low risk; eligible after probe acceptance
- Notes: No additional notes.

### Hacker News Top Stories (`hackernews-top`)

- Nature: `community`
- Roles: `discovery`, `engagement`, `context`
- Primary access: `public_api` - https://hacker-news.firebaseio.com/v0/topstories.json
- Fallback access: none documented
- Expected fields: author, canonical_url, engagement, published_at, title
- Observed missing fields: none
- Probe: `success`; Parsed 5 JSON samples; field completeness 100%
- Risk breakdown: terms=1, authentication=0, stability=1, data_quality=3, operating_cost=0; total=5 (`low`)
- Recommendation: Low risk; eligible after probe acceptance
- Notes: No additional notes.

### Hugging Face Blog (`huggingface-blog`)

- Nature: `first_party`
- Roles: `discovery`, `evidence`
- Primary access: `rss` - https://huggingface.co/blog/feed.xml
- Fallback access: none documented
- Expected fields: canonical_url, published_at, summary, title
- Observed missing fields: summary
- Probe: `degraded`; Parsed 5 feed samples; field completeness 75%
- Risk breakdown: terms=1, authentication=0, stability=1, data_quality=1, operating_cost=0; total=3 (`low`)
- Recommendation: Low risk; eligible after probe acceptance
- Notes: No additional notes.

### Hugging Face Transformers Releases (`transformers-releases`)

- Nature: `first_party`
- Roles: `discovery`, `evidence`
- Primary access: `rest_api` - https://api.github.com/repos/huggingface/transformers/releases
- Fallback access: none documented
- Expected fields: author, canonical_url, published_at, summary, title
- Observed missing fields: none
- Probe: `success`; Parsed 5 JSON samples; field completeness 100%
- Risk breakdown: terms=1, authentication=1, stability=1, data_quality=1, operating_cost=0; total=4 (`low`)
- Recommendation: Low risk; eligible after probe acceptance
- Notes: No additional notes.

### Microsoft Research (`microsoft-research`)

- Nature: `first_party`
- Roles: `discovery`, `evidence`
- Primary access: `rss` - https://www.microsoft.com/en-us/research/feed/
- Fallback access: none documented
- Expected fields: canonical_url, published_at, summary, title
- Observed missing fields: none
- Probe: `success`; Parsed 5 feed samples; field completeness 100%
- Risk breakdown: terms=1, authentication=0, stability=1, data_quality=1, operating_cost=0; total=3 (`low`)
- Recommendation: Low risk; eligible after probe acceptance
- Notes: No additional notes.

### Mistral Common Releases (`mistral-common-releases`)

- Nature: `first_party`
- Roles: `discovery`, `evidence`
- Primary access: `rest_api` - https://api.github.com/repos/mistralai/mistral-common/releases
- Fallback access: none documented
- Expected fields: author, canonical_url, published_at, summary, title
- Observed missing fields: none
- Probe: `success`; Parsed 5 JSON samples; field completeness 100%
- Risk breakdown: terms=1, authentication=1, stability=1, data_quality=1, operating_cost=0; total=4 (`low`)
- Recommendation: Low risk; eligible after probe acceptance
- Notes: No additional notes.

### NVIDIA CUDA Python Releases (`cuda-python-releases`)

- Nature: `first_party`
- Roles: `discovery`, `evidence`
- Primary access: `rest_api` - https://api.github.com/repos/NVIDIA/cuda-python/releases
- Fallback access: none documented
- Expected fields: author, canonical_url, published_at, summary, title
- Observed missing fields: none
- Probe: `success`; Parsed 5 JSON samples; field completeness 100%
- Risk breakdown: terms=1, authentication=1, stability=1, data_quality=1, operating_cost=0; total=4 (`low`)
- Recommendation: Low risk; eligible after probe acceptance
- Notes: No additional notes.

### NVIDIA Developer Blog (`nvidia-developer-blog`)

- Nature: `first_party`
- Roles: `discovery`, `evidence`
- Primary access: `atom` - https://developer.nvidia.com/blog/feed/
- Fallback access: none documented
- Expected fields: canonical_url, published_at, summary, title
- Observed missing fields: none
- Probe: `success`; Parsed 5 feed samples; field completeness 100%
- Risk breakdown: terms=1, authentication=0, stability=1, data_quality=1, operating_cost=0; total=3 (`low`)
- Recommendation: Low risk; eligible after probe acceptance
- Notes: No additional notes.

### OpenAI News (`openai-news`)

- Nature: `first_party`
- Roles: `discovery`, `evidence`
- Primary access: `rss` - https://openai.com/news/rss.xml
- Fallback access: none documented
- Expected fields: canonical_url, published_at, summary, title
- Observed missing fields: none
- Probe: `success`; Parsed 5 feed samples; field completeness 100%
- Risk breakdown: terms=1, authentication=0, stability=1, data_quality=1, operating_cost=0; total=3 (`low`)
- Recommendation: Low risk; eligible after probe acceptance
- Notes: Official first-party announcements; does not represent independent verification.

### OpenAI Python SDK Releases (`openai-python-releases`)

- Nature: `first_party`
- Roles: `discovery`, `evidence`
- Primary access: `rest_api` - https://api.github.com/repos/openai/openai-python/releases
- Fallback access: none documented
- Expected fields: author, canonical_url, published_at, summary, title
- Observed missing fields: none
- Probe: `success`; Parsed 5 JSON samples; field completeness 100%
- Risk breakdown: terms=1, authentication=1, stability=1, data_quality=1, operating_cost=0; total=4 (`low`)
- Recommendation: Low risk; eligible after probe acceptance
- Notes: No additional notes.

### Qwen3 Releases (`qwen3-releases`)

- Nature: `first_party`
- Roles: `discovery`, `evidence`
- Primary access: `rest_api` - https://api.github.com/repos/QwenLM/Qwen3/releases
- Fallback access: none documented
- Expected fields: author, canonical_url, published_at, summary, title
- Observed missing fields: author, canonical_url, published_at, summary, title
- Probe: `degraded`; Parsed 0 JSON samples; field completeness 0%
- Risk breakdown: terms=1, authentication=1, stability=1, data_quality=2, operating_cost=0; total=5 (`low`)
- Recommendation: Low risk; eligible after probe acceptance
- Notes: No additional notes.

### Reddit Artificial (`reddit-artificial`)

- Nature: `community`
- Roles: `discovery`, `engagement`, `context`
- Primary access: `rest_api` - https://oauth.reddit.com/r/artificial/new
- Fallback access: none documented
- Expected fields: author, canonical_url, engagement, published_at, title
- Observed missing fields: author, canonical_url, engagement, published_at, title
- Probe: `blocked`; REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET are required for official OAuth access
- Risk breakdown: terms=3, authentication=3, stability=2, data_quality=3, operating_cost=1; total=12 (`medium`)
- Recommendation: Medium risk; fallback method required
- Notes: No additional notes.

### Reddit LocalLLaMA (`reddit-localllama`)

- Nature: `community`
- Roles: `discovery`, `engagement`, `context`
- Primary access: `rest_api` - https://oauth.reddit.com/r/LocalLLaMA/new
- Fallback access: none documented
- Expected fields: author, canonical_url, engagement, published_at, title
- Observed missing fields: author, canonical_url, engagement, published_at, title
- Probe: `blocked`; REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET are required for official OAuth access
- Risk breakdown: terms=3, authentication=3, stability=2, data_quality=3, operating_cost=1; total=12 (`medium`)
- Recommendation: Medium risk; fallback method required
- Notes: No additional notes.

### Reddit MachineLearning (`reddit-machinelearning`)

- Nature: `community`
- Roles: `discovery`, `engagement`, `context`
- Primary access: `rest_api` - https://oauth.reddit.com/r/MachineLearning/new
- Fallback access: none documented
- Expected fields: author, canonical_url, engagement, published_at, title
- Observed missing fields: author, canonical_url, engagement, published_at, title
- Probe: `blocked`; REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET are required for official OAuth access
- Risk breakdown: terms=3, authentication=3, stability=2, data_quality=3, operating_cost=1; total=12 (`medium`)
- Recommendation: Medium risk; fallback method required
- Notes: No additional notes.

### Techmeme Feed (`techmeme-feed`)

- Nature: `aggregator`
- Roles: `discovery`
- Primary access: `rss` - https://www.techmeme.com/feed.xml
- Fallback access: none documented
- Expected fields: canonical_url, published_at, summary, title
- Observed missing fields: none
- Probe: `success`; Parsed 5 feed samples; field completeness 100%
- Risk breakdown: terms=2, authentication=0, stability=2, data_quality=4, operating_cost=1; total=9 (`medium`)
- Recommendation: Medium risk; fallback method required
- Notes: Discovery only; links may be aggregation pages and require origin resolution.


## Policy

YAML remains the audited source of truth; probe results never edit it.
