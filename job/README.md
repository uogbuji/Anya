Your job definitions go here. Apart from `example/`, everything in `job/` is gitignored, so jobs (and any proprietary helpers) stay out of the repo.

Each subdirectory is one job:

- **`anya.toml`** — job metadata: `title`, `frequency`, `phase`, etc.
- **`controller.py`** — the job itself: a Python program that gathers data (`anya.fetchers`), asks the LLM specific questions (`anya.inference`), and prints its report to stdout.
- **`anya.loom.toml`** — the job's prompts, in WordLoom format.
- **`.env`** (optional) — per-job environment variables.

A `_`-prefixed directory such as `_lib/` holds shared code rather than a job; any controller can `from _lib import ...`. Put job tests beside the code (e.g. `_lib/test/`) and run them with `anya test`.

See `example/`, and the "Job structure" section of the main README for the details. The example is skipped by default because its `phase` is `ignore`; run it with `anya run --phases=default,ignore`.
