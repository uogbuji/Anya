# Changelog
<!--
Notable changes to Onya are recorded here. Format based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/). Project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

For interim changes not yet earmarked for a particular release, can use this header at the top:
## [Unreleased]
-->

Note: versions before 0.4.0 were never formally released; their entries are kept as a working log.

## [0.4.0] - 20261124: Python 3.14 version floor bump, and concomitant fixes.

Will be the first actual GitHub release.

### Added
- `anya test [--job_dir=job] [--args='...']` runs the tests that live in a job directory (e.g. `job/_lib/test/`), which anya's own `pytest` run no longer collects. pytest runs in a subprocess with the job root first on `PYTHONPATH`, as the executor sets it for controllers, so job tests can `from _lib import ...` without a `sys.path` conftest.

- `drop_tabindex_minus_one=True` option on the `plain` and `reddit` fetchers (and `clean_html`) to also strip `tabindex="-1"` elements. Off by default.

- A job run record, `data/job-runs.json` (`config.toml [paths] runs`). A job is due when it hasn't run since its most recent scheduled day, so a missed run happens at the next tick, and restarts or extra ticks don't re-run jobs. Failed runs are recorded too, and `--select_jobs` runs aren't recorded. Without a record, a job runs on its scheduled days, as before.
- `frequency` accepts the aliases `sundays`, `saturdays`, `weekdays`, `monday`, and `mondays`.

- `anya.logs.configure_logging()`: one logging policy for the CLI and controllers: logs to stderr, plain tracebacks without local variables, info level by default (`ANYA_LOG_LEVEL` to change). `import anya` applies it inside controller processes. The executor now passes a successful controller's stderr to the runner's log; it used to be discarded.
- Controllers can read long-term memory: the executor sets `ANYA_MEMORY_FILE`, and `anya.memory.read_memory()` reads it, optionally only one job's entries (`job_id=`).
- `client=` on every fetcher, searcher, `fetch_rss`, `fetch_http`, and the `resend`/`unosend` email providers: pass an `httpx.AsyncClient` (e.g. one on `httpx.MockTransport` in tests) instead of letting each call make its own.
- `verify=` on the `plain` fetcher (default `True`) to disable TLS certificate checks for a specific site.
- `register_fetcher(name, factory)` and `register_searcher(name, factory)` in `anya.fetchers` to add fetch methods and search providers; they work with `create_fetcher`/`create_searcher` and `anya fetch --method`.

### Changed
- **Python 3.14 is now the minimum** (was 3.12). The Docker image's base moves to `python:3.14-slim`, pinned by digest as before.
- HTML cleaning and HTML→Markdown conversion now live in anya (`anya.fetchers._html`), adapted from OgbujiPT's `ogbujipt.text.html` onto selectolax's lexbor backend. This is a temporary copy until the code is available in a released Amara. The `ogbujipt` git dependency is gone, and the Docker builder no longer needs `git`.
- Requires `selectolax>=1.0.2` and `hishel>=2.0`.
- `pytest` now collects only `test/` and skips tests marked `integration` by default (run those with `pytest -m integration`). Previously it also picked up tests under the gitignored `job/` tree. Test tooling is available as the `test` extra: `uv pip install '.[test]'`.

- Relative paths in `config.toml [paths]` now resolve against the config file's directory, not the current working directory. For the usual layout (`config.toml` beside `data/`) nothing moves.
- LLM calls: SDK retries are capped at 1 (was the SDKs' default of 2), and each `inference()` call has an overall 240s limit covering retries and the JSON-repair second request, surfacing as `UpstreamAPIError`. Previously a stall could take up to 270s per request, or about 540s for a structured-output call, against the executor's 600s ceiling. LLM clients are now closed after each call.
- `---RESOLVED---` handling is narrower and safer. Each line is one phrase (min. 8 characters), not fragments split on commas, "and", and "or", and a job only removes its own memory entries, never another job's. Resolutions apply before the same run's new `---MEMORY---` entries are added. `prune_memory()` takes the job id and returns the number removed.
- Memory writes hold a file lock, as blotter writes do. A lock timeout on memory or blotter shows as a "System issue" line in the report instead of failing the job. `BlotterLockError` is now a subclass of a general `StateLockError`.
- The default system prompt for `inference()` moved from Python source into a packaged WordLoom file (`anya/resources/inference.loom.toml`), replacing `anya.inference.DEFAULT_SYSTEM_PROMPT` with `default_system_prompt()`. Job prompt files are reloaded when they change on disk.
- `WebFetcher`, `WebSearcher`, and `Scheduler` are now `typing.Protocol`s rather than abstract base classes, so implementations need no base class. `create_fetcher`, `create_searcher`, and `get_scheduler` look names up in registries (`FETCHERS`, `SEARCHERS`, `SCHEDULERS`) instead of `if` chains. `create_fetcher()` defaults to `'plain'` (`'simple'` remains an alias).
- OpenAI-compatible backends: JSON-schema requests use strict mode only when the schema qualifies, and requests to OpenAI's own API send `max_completion_tokens` instead of the deprecated `max_tokens`.
- An unknown `frequency` in `anya.toml` is now a job load error (reported in the email) instead of silently running on every tick.
- Controllers may emit several `---MEMORY---` / `---RESOLVED---` blocks; each type's blocks are joined.

### Removed
- APScheduler support (`anya serve --scheduler=apscheduler` and the `scheduler-apscheduler` extra). It was only used as an interval timer, which the built-in asyncio scheduler already provides.
- The `scheduler-cron`, `scheduler-schedule`, `imap`, and `all` extras. No code used them.

### Fixed
- HTML fetching (`plain` and `reddit` methods) failed on fresh installs: selectolax 1.0 removed the parser backend that `ogbujipt.text.html` imports.
- After upgrading to hishel 2, every cached fetch (`plain`, `rss`, `reddit`) failed with "This database is a Hishel 1.x cache", until someone deleted the cache file by hand. An old 1.x cache is now moved aside (renamed with a `.hishel1-<timestamp>` suffix, with a logged warning) and a fresh one started.
- Content hidden by an inline `style="display: none"` (or `visibility: hidden`) is now removed before conversion. The inline style was parsed as a stylesheet, so it never matched.
- HTML cleaning no longer drops elements with `tabindex="-1"` by default; sites commonly put that on the main content container.
- `reddit` fetcher: Reddit's login wall (a redirect to `/login` serving a 200 "Welcome to Reddit" page) was returned as successful content, and the RSS fallback would have parsed the same page as an empty feed. Both paths now detect the wall and report it as a failure. The fallback also reuses one HTTP client and now returns the feed's title.
- Report emails put job output into the HTML body unescaped. Since reports carry LLM output over fetched web content, a prompt-injected page could add links, images, or tracking pixels to the email. Report text is now HTML-escaped.
- One job that failed to load (unparseable `anya.toml`, missing entry file, unsupported type) aborted the whole tick, so no job ran. Each job now loads independently, and a load failure is logged and included in the report email (as `ERROR: job failed to load - ...`), filtered by `--select_jobs`/`--exclude_jobs` like other jobs.
- The HTTP cache wasn't shared: its default path was resolved relative to each controller's working directory (its job dir), giving every job its own cache under `job/<id>/data/`. It's now one cache beside `config.toml`. Old per-job `job/*/data/http-cache.sqlite` files can be deleted.
- The CLI looked for `./config.toml` before `$ANYA_CONFIG_FILE`, the reverse of the documented order (and of what controllers use). Both now use `--config`, then `$ANYA_CONFIG_FILE`, then `./config.toml`.
- Report text that a controller printed after a `---MEMORY---` or `---RESOLVED---` block was dropped from the report. Only the blocks themselves are removed now, and an unterminated marker no longer swallows the rest of the report.
- `weekly`, `saturday`, and `sunday` jobs could be skipped for a whole period. The scheduler waits a full interval after each tick finishes, so tick times drift later by the jobs' runtime; once a tick slid past midnight (e.g. Sunday 23:50 to Tuesday 00:05), a Monday-only job never saw a Monday. Missed runs now catch up via the run record.
- Every restart of `anya serve` (e.g. a container restart or redeploy) re-ran all of the day's jobs, sending duplicate reports. The run record prevents this.
- The asyncio scheduler left a pending helper task behind on every tick.
- In controllers, log lines from anya's own library (e.g. "TAVILY_API_KEY not set", the HTTP cache migration notice, RSS debug output) went to stdout, so they appeared in the emailed and blottered report.
- Memory parsing cut an entry in two at any `---` line in its content, and pruning silently deleted any text that didn't look like an entry.
- A missing prompt id raised a `KeyError` that listed every prompt's full body, not just the prompt names.
- Structured-output calls to OpenAI failed with HTTP 400 for any schema not written for strict mode (e.g. an object with optional properties), because `strict: true` was always sent. Such schemas are now sent non-strict.
- OpenAI reasoning models rejected requests because of `max_tokens`.
- `anya fetch --method=<unknown>` ended in a traceback; it now prints the valid methods.
- A refused connection to an LLM backend (e.g. a local server that's down) escaped as a raw SDK error; it's now an `UpstreamAPIError`.
- `base_url` in an Anthropic backend's `config.toml` entry was ignored.
- `inference()`: the Anthropic and OpenAI-compatible clients now set an explicit 90s request timeout instead of inheriting the SDKs' 600s default, which matched the executor's own 600s controller timeout. A single stalled upstream LLM call could silently eat a job's entire time budget, surfacing only as `TimeoutError: Controller ... exceeded 600s` with no application-level error. A stall now raises `UpstreamAPIError` instead.

### Security
- The `plain` fetcher disabled TLS certificate verification on every request (`verify=False`), so anyone on the network path could alter fetched content before it reached the LLM. Verification is now on.
- In controllers, exception tracebacks were rendered with local variables (structlog's default Rich formatter), which could print API keys from backend configs or request headers into logs. Controllers now use the same plain, locals-free tracebacks as the CLI.
- Report emails now HTML-escape job output (see Fixed), so prompt-injected web content can't add markup, links, or tracking images.

## [0.3.1] - 20260702

### Added
- `anya fetch <target> [--method plain] [--config path]`: exercise a single source/method and print the fetcher's markdown to stdout — an eye test for exactly what a job receives from a source before any LLM extraction. `--method` covers the fetch methods (`plain` (default) | `crawl4ai` | `reddit` | `rss`, `target` is a URL) and the search methods (`tavily` | `brave`, `target` is a query), dispatching like a job does (`create_fetcher`/`create_searcher`) and reading `crawl4ai_base_url`/result counts/UA from `config.toml`. Only `result.markdown` goes to stdout (pipeable); a status line (method, source, title, length, ok/FAILED) goes to stderr, and a failed fetch exits 1. Noisy CSS-parser warnings from HTML cleaning are silenced for a clean read.
- Web search ("SERP") fetchers in `anya.fetchers`: `search_web(query, provider=...)` / `create_searcher(provider)` with **tavily** and **brave** providers. A searcher takes a query (not a URL) and returns a `FetchResult` whose markdown lists each result's title/URL/snippet — so search results feed the same extract→validate pipeline as page fetchers, with the result URLs serving as the allow-list. Keys are secrets in env (`TAVILY_API_KEY` / `BRAVE_API_KEY`); result counts are non-secret config (`config.toml [fetch] tavily_max_results` / `brave_max_results`, default 10). A missing key is a soft failure (logged warning, `success=False`) rather than a crash. Reddit needs no new searcher — point the existing `reddit` fetcher at a subreddit search URL. `compose.yml` now also passes `TAVILY_API_KEY`/`BRAVE_API_KEY` through to the container (empty by default) so search-based jobs work in the Docker deploy.
- Shared code across jobs via `job/_lib/`. A `_`-prefixed directory under `job/` is treated as shared code, not a job (discovery skips it), and when a `_lib/` is present the executor prepends the `job/` root to each controller's `PYTHONPATH` so any controller can `from _lib import ...` to reuse logic without copy-paste. Gitignored by default like the rest of `job/`, so it doubles as a home for proprietary helpers kept out of the repo.

### Changed
- `doc/DEPLOYMENT.md`: clarified the UID-10001 ownership step that prevents per-job-state `PermissionError`. `rsync -a` preserves the laptop UID, so the deploy now re-chowns the host job/data dirs to 10001 after each sync (throwaway root container — no host path needed; re-run on every job re-sync). `rsync --chown=10001:10001` is offered as a one-step alternative for rsync 3.1+, with a heads-up that **stock macOS rsync (2.6.9) rejects `--chown`** (install a current rsync from source if you want it). Checklist + "Host dir ownership" section updated to match.

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
