Your actual job definitions go here.

Each subdirectory is one job. Required:

- **MAIN.md** — Core prompt, instructions, and optional `fetch:` / `rss:` lines. See main README for full MAIN.md format (id, phase, frequency, inline actions, etc.)

Optional per job:

- **fetch.py** — Runs before the LLM; stdout becomes context
- **.env** — Per-job env (API keys, etc.)
- **`*.py`** — Any .py files run for read-only data gathering (use `anya.fetchers` for web fetching)

See `example/`. Notice that it gets skipped by default because it's phase is set to `ignore`.
