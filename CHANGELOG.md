# Changelog

Notable changes to  Format based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/). Project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

<!-- 
## [Unreleased]
 -->

## [0.3.0] - 20260628

### Added
- Docker Compose deployment for a single host (e.g. a DigitalOcean Droplet via a remote Docker context): `Dockerfile`, `compose.yml`, `.dockerignore`, and `doc/DEPLOYMENT.md`. The image is a generic anya runtime; the job dir (`${ANYA_JOB_DIR:-./job}`) and `data/` are deployer-curated, bind-mounted host content (so jobs change without a rebuild and per-job state persists), `config.toml` is a baked default overridable by a mount, and secrets are injected at runtime (`op run` / `.env`). Optional `crawl4ai` service behind a `crawl` profile.
- `anya serve` refuses to start (exit 2) when its job directory is missing or empty, instead of ticking forever with zero jobs — surfaces a botched/absent bind mount immediately. `anya run` logs a warning in the same case but still completes (a single empty tick is harmless).
- `env.example`: template for the deploy `.env` documenting every var `compose.yml` interpolates (LLM keys, email provider, deploy knobs) and both the `op run` (op:// refs) and concrete-value flows. Notes the remote-context `ANYA_JOB_DIR` gotcha (use an absolute path on the remote host).
- `doc/DEPLOYMENT.md`: a Maintenance section — reclaiming build cache from repeated `--build` (with shared-host prune-safety caveats), updating the anya and crawl4ai images, and reading health/liveness. Defers host-wide concerns (cross-stack disk hygiene, image-upgrade monitoring, supply-chain) to a separate droplet-maintenance guide.
- `anya run` / `anya serve`: `--select_jobs` and `--exclude_jobs` (comma-separated job ids) to run or skip specific jobs on top of `--phases`. `--select_jobs` bypasses frequency checks for dev/testing.

### Changed
- **Clean split of config from secrets (breaking).** All non-sensitive settings now live in `config.toml`; the environment holds only secrets (API keys). New `config.toml` sections: `[email]` (`provider`/`to`/`from`), `[fetch]` (`crawl4ai_base_url`/`reddit_user_agent`), `[paths]` (`blotter`/`memory`/`http_cache`), `[blotter]` (`lock_timeout`). A process-wide `anya.config.get_config()` accessor is the single way modules read settings. CLI flags (`--email_to`/`--blotter`/`--memory`) still override their `config.toml` defaults. `compose.yml`/`env.example` now carry only secrets + deploy knobs; `config.example.toml` documents the new sections.
- A `config.toml` defining at least one `[models.backends.*]` is now **required** — the env-only backend synthesis is gone (see Removed). Secrets referenced in `config.toml` via `${ENV_VAR}` still expand; a *literal* secret in a known-secret field (`api_key`) now logs a warning.
- Pin the `python:3.12-slim` base image by digest (the multi-arch index) in both Dockerfile stages, for reproducible builds independent of the mutable tag. Refresh with `docker buildx imagetools inspect python:3.12-slim`.
- Pin the optional `crawl4ai` image by digest (`unclecode/crawl4ai:basic@sha256:…`) instead of the bare mutable tag, so a moved tag can't change what runs; the tag is kept as a readable label. Refresh with `docker buildx imagetools inspect unclecode/crawl4ai:basic`.
- Depend on `ogbujipt`'s lightweight HTML→Markdown profile (pinned to git `main` until released, dropping the explicit `tiktoken` dep). The previous PyPI build transitively dragged in `torch`/`transformers`/`tiktoken`, ballooning the deploy image to ~5 GB; it's now ~276 MB. Requires `[tool.hatch.metadata] allow-direct-references` for the git pin.
- `inference()` now appends the current date to the system prompt on every call (with a `now=` override for deterministic tests/replay). Inference providers don't set the date and the model's training prior guesses an earlier year, so any prompt reasoning about deadlines, recency, or relative dates was silently wrong (e.g. a deadline 4 days out described as "roughly a year out"). Making the date ambient means jobs no longer need to plumb it into their prompts.

### Removed
- Non-secret config env vars, now read from `config.toml`: `ANYA_EMAIL_TO`, `ANYA_EMAIL_PROVIDER`, `RESEND_FROM`, `UNOSEND_FROM`, `CRAWL4AI_BASE_URL`, `REDDIT_USER_AGENT`, `BLOTTER_FILE`, `BLOTTER_LOCK_TIMEOUT`, `ANYA_HTTP_CACHE`.
- Env-var LLM-backend synthesis: `LLM_PROVIDER`, `LLM_MODEL`, `LLM_BASE_URL`, `LLM_API_KEY`, `OPENAI_API_BASE`. Define backends in `config.toml [models.backends.*]` instead. Secret keys are still read from env (`ANTHROPIC_API_KEY`/`OPENROUTER_API_KEY`/`OPENAI_API_KEY`, `RESEND_API_KEY`/`UNOSEND_API_KEY`).

## [0.2.0] - 20260608

- Rearchitect for general workflow shapes: deterministic controller per job + `inference(promptid, context, **kwargs)` library call; prompts moved to WordLoom (`anya.loom.toml` — `.loom.toml` suffix so editors auto-detect TOML); job metadata moved to `anya.toml`.
- `inference()` is text-in / text-or-JSON-out. Tool-call kwargs (`tools=`, `tool_choice=`, etc.) are refused at dispatch time.
- Structured outputs supported on every backend: Anthropic via tool-use coercion; OpenAI-compatible via `response_format` with one post-hoc parse-and-retry as a fallback.
- Top-level `config.toml` with model alias registry (`cheapest`, `fast`, `best-reasoning`, etc.) mapping to concrete backends.
- Add **OpenRouter** as a first-class backend (`provider = "openrouter"` sugar; auto-fills base_url and `OPENROUTER_API_KEY`). OpenRouter + local oMLX are the preferred options; Anthropic direct still supported.
- Drop `mlx_lm` support — local inference is via oMLX fronted as an OpenAI-compatible server (grammar-capable build required).
- Drop `MAIN.md`, `---ACTION---` blocks, and `fetch:`/`rss:` inline directives — controllers do their own gather logic now.
- Pluggable email providers (`anya.email`); **Resend** is now the default (`RESEND_API_KEY`, `RESEND_FROM`). Unosend kept as an opt-in provider. Selection via `ANYA_EMAIL_PROVIDER` env; custom providers register via `anya.email.register_provider`.
- `UpstreamAPIError` wraps non-2xx responses from LLM providers, so a 402/429/etc. surfaces as a single-line message (with the provider's specific reason) instead of a 50-line traceback in the user's email/blotter. Exported from `anya`.
- `random-reminders` controller now skips malformed `candidates.txt` lines (writing a warning to stderr) instead of crashing the whole run.
- New `reddit` fetcher method: rewrites any `*.reddit.com` URL (incl. `www.`) to `old.reddit.com` with a real `User-Agent`, falls back to the URL's `.rss` feed when blocked. No crawl4ai dependency. Override the UA via `REDDIT_USER_AGENT`.
- New `rss` fetcher method: fetches an RSS/Atom feed (httpx + `feedparser`) and returns a markdown summary of entries. Fixes `news-reader` crash on `method = "rss"` candidates.
- All GET fetchers (`plain` / `rss` / `reddit`) now share an RFC 9111 HTTP cache via `hishel` — conditional GET (`If-None-Match` / `If-Modified-Since`), `Cache-Control` / `Vary` honored. SQLite-backed at `data/http-cache.sqlite`; override with `ANYA_HTTP_CACHE`.
