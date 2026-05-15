# Changelog

Notable changes to  Format based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/). Project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

<!--
## [Unreleased]
-->

## [0.2.0] - 20260514

- Rearchitect for general workflow shapes: deterministic controller per job + `inference(promptid, context, **kwargs)` library call; prompts moved to WordLoom (`anya.loom`); job metadata moved to `anya.toml`.
- `inference()` is text-in / text-or-JSON-out. Tool-call kwargs (`tools=`, `tool_choice=`, etc.) are refused at dispatch time.
- Structured outputs supported on every backend: Anthropic via tool-use coercion; OpenAI-compatible via `response_format` with one post-hoc parse-and-retry as a fallback.
- Top-level `config.toml` with model alias registry (`cheapest`, `fast`, `best-reasoning`, etc.) mapping to concrete backends.
- Add **OpenRouter** as a first-class backend (`provider = "openrouter"` sugar; auto-fills base_url and `OPENROUTER_API_KEY`). OpenRouter + local oMLX are the preferred options; Anthropic direct still supported.
- Drop `mlx_lm` support — local inference is via oMLX fronted as an OpenAI-compatible server (grammar-capable build required).
- Drop `MAIN.md`, `---ACTION---` blocks, and `fetch:`/`rss:` inline directives — controllers do their own gather logic now.
- Pluggable email providers (`anya.email`); **Resend** is now the default (`RESEND_API_KEY`, `RESEND_FROM`). Unosend kept as an opt-in provider. Selection via `ANYA_EMAIL_PROVIDER` env; custom providers register via `anya.email.register_provider`.
- `UpstreamAPIError` wraps non-2xx responses from LLM providers, so a 402/429/etc. surfaces as a single-line message (with the provider's specific reason) instead of a 50-line traceback in the user's email/blotter. Exported from `anya`.
- `random-reminders` controller now skips malformed `candidates.txt` lines (writing a warning to stderr) instead of crashing the whole run.
- New `reddit` fetcher method: rewrites to `old.reddit.com` with a real `User-Agent`, falls back to the URL's `.rss` feed when blocked. No crawl4ai dependency. Override the UA via `REDDIT_USER_AGENT`.
