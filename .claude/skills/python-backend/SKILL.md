---
name: python-backend
description: Use when building, reviewing, or debugging a long-running Python service — web back end, worker, bot, or async daemon. Covers retaining fire-and-forget asyncio tasks, secret-safe structlog tracebacks, and read-only SQLite over read-only mounts. Load alongside python, which holds the style and packaging rules.
---

# Python Backend Services

## Purpose
Runtime correctness and security for Python code that stays up: services, workers, bots,
and async daemons. Assumes the [python](../python/SKILL.md) skill for style, packaging, and
the dev loop — this one only adds what goes wrong once the process is long-lived.

## Concurrency model
Default to **asyncio for I/O-bound work** (HTTP, DB, sockets, queues) and **processes, not threads, for anything broader** (CPU-bound work, isolation, parallelism across cores):

- Scale out with `multiprocessing` / `concurrent.futures.ProcessPoolExecutor` (or `loop.run_in_executor` with a process pool from async code) rather than threading.
- Between processes, prefer **message passing** (`multiprocessing.Queue`/`Pipe`, or an external queue) and, for bulk data, **shared memory** (`multiprocessing.shared_memory`) over shared mutable state guarded by locks.
- Threads are a last resort for blocking calls you can't make async; wrap them with `asyncio.to_thread` and keep them out of the service's design. Never block the event loop with sync I/O or CPU work.

## Service & async hardening
Recurring, easy-to-miss correctness/security gotchas in long-running services (and the CLIs that drive them):

- **Retain fire-and-forget tasks.** `asyncio.create_task(coro())` returns a task the
  event loop holds only *weakly* — under GC pressure it can be collected mid-`await`,
  silently dropping the work (a webhook enqueue, a deferred Slack post). Keep a strong
  reference until it finishes:
  ```python
  _tasks: set[asyncio.Task] = set()

  def spawn_background(coro):
      t = asyncio.create_task(coro)
      _tasks.add(t)
      t.add_done_callback(_tasks.discard)
      return t
  ```
- **Secret-safe tracebacks.** `structlog.dev.ConsoleRenderer()` (Rich) renders local
  variables in tracebacks — which leaks secrets, since API keys live in headers dicts,
  settings objects, etc. Always pass `exception_formatter=structlog.dev.plain_traceback`,
  and define a single `configure_logging()` so the policy can't drift between entry
  points — one copy that forgets it leaks in that service's logs.
- **Read-only SQLite over a read-only mount.** Open with a `file:` URI in `mode=ro` so the
  connection can never write and won't auto-create a missing file:
  ```python
  dsn = Path(path).resolve().as_uri() + '?mode=ro'   # as_uri() percent-encodes the path
  await aiosqlite.connect(dsn, uri=True)
  ```
  Build the URI with `Path.as_uri()`, not an f-string: a raw `file:{path}?mode=ro`
  truncates the path at a literal `?` and opens the wrong file. And `aiosqlite.connect`
  on a bare path *auto-creates* an empty DB — so a missing mount silently looks like an
  empty store; `mode=ro` makes it fail loudly instead.

## Related
- [python](../python/SKILL.md) — style, packaging, `uv`/hatchling dev loop.
- [docker-compose-deploy](../docker-compose-deploy/SKILL.md) — running the service on a host (mounts, secrets, healthchecks).
- [testing](../testing/SKILL.md) — injectable `httpx.AsyncClient`, in-memory store implementations.


