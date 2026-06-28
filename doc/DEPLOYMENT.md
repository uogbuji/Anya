# Deploying anya with Docker Compose

anya runs as a single long-lived worker (`anya serve`): a scheduler that ticks on an
interval, runs due jobs, and emails / blotters their reports. There is **no inbound port** —
it makes outbound calls to LLM providers and email APIs only. That makes it a good fit for a
one-host Docker Compose deploy with no CI/CD pipeline: you build locally and run the
container on a remote host (initial target: a DigitalOcean Droplet) over a remote Docker
context.

Files: [`Dockerfile`](./Dockerfile), [`compose.yml`](./compose.yml), [`.dockerignore`](./.dockerignore).

## The deploy model

- **One command, no pipeline.** `docker compose up -d --build` builds the image on your
  machine, ships the layers over SSH to the host's Docker daemon, and (re)starts the service.
- **Same `compose.yml` locally and in prod.** Switch targets with the Docker *context*, not
  by editing files.
- **Secrets injected at runtime, never baked into the image.** Wrap the deploy in a secrets
  manager (`op run` for 1Password, `bws run` for Bitwarden), or rely on Compose auto-reading
  a concrete `./.env`. The image never contains a key.

## What is baked vs. mounted vs. injected

The image is a **generic anya runtime** — it contains the code, not your jobs or state.
Everything deploy-specific is mounted or injected:

| Thing | How | Why |
|-------|-----|-----|
| anya package | installed into a venv in the image (non-editable wheel) | the real distribution, frozen per build |
| `job/` dir | **bind mount** `${ANYA_JOB_DIR:-./job}:/app/job` (read-write) | deployer-curated; jobs change without a rebuild, and per-job state persists |
| `data/` (blotter, memory, HTTP cache) | **bind mount** `./data:/app/data` | runtime-populated; persists across restarts and rebuilds |
| `config.toml` (model aliases/backends) | **baked** default; mount to override | sensible default frozen with the image; mount `:ro` to change backends without rebuilding |
| API keys, `RESEND_*`, email-to, interval | **injected** as env at `up` time | secrets/config that must not live in the image |

## Curating the job dir

You decide what runs by curating the directory you mount at `/app/job`. Each immediate
subdirectory with an `anya.toml` is a job; anything else is ignored. Because it's the deploy
artifact (not the image), changing jobs is a **remount/restart, not a rebuild**.

- **Default** (`./job`): the repo's own job dir. Jobs are private — everything under `job/*`
  is gitignored except `job/example/` — so the host copy is yours to curate (rsync it over,
  keep a deploy branch, or maintain it directly on the host).
- **Point elsewhere**: set `ANYA_JOB_DIR` to any host path holding a curated set, e.g.
  `ANYA_JOB_DIR=/srv/anya/jobs.prod`. Drop in only the jobs that host should run.

```bash
# Ship a curated set living outside the repo:
ANYA_JOB_DIR=/srv/anya/jobs.prod \
  op run --env-file=.env -- docker compose up -d
```

> **Fail-loud, not silent.** Over a remote Docker context a missing bind-mount source is
> created as an *empty* directory rather than erroring — which would mean "ran zero jobs"
> with no signal. `anya serve` guards against this: if `/app/job` has no jobs it **refuses to
> start** (exit 2) with a message, so a botched mount surfaces immediately in `docker logs`.

> **Which jobs *run* vs. which are *present*** is still separate: `ANYA_PHASES` (default
> `default`) and per-job `frequency` gate each tick. Ad-hoc:
> `docker compose run --rm anya run --select_jobs=grant-hunter` bypasses frequency.

## One-time: remote Docker context for the Droplet

Use key-based SSH as a non-interactive user; never set a root password to expedite access.

```bash
docker context create anya-droplet --docker "host=ssh://root@<droplet-ip>"
docker context use anya-droplet     # all docker/compose commands now target the Droplet
docker context show                 # verify
docker ps                           # should list the Droplet's containers (likely none yet)
# switch back to your laptop's daemon when done:
docker context use default
```

DNS / firewall: anya needs **outbound 443** only (LLM + email APIs). No inbound ports are
required unless you enable the optional crawl4ai service (which stays internal to the stack).

## Secrets

`compose.yml` reads secrets via `${VAR}` interpolation. Two supported flows:

```bash
# 1Password (recommended): .env holds op:// reference URIs, resolved only for this child:
op run --env-file=.env -- docker compose up -d --build

# Concrete .env: Compose auto-reads ./.env for ${VAR} interpolation, so plain works:
docker compose up -d --build
```

`.env`/compose carries **only secrets and deploy knobs** — every non-secret setting (email
provider/sender/recipients, fetcher URLs, paths) lives in `config.toml`. Secrets (set only
what your `config.toml` resolves to): `OPENROUTER_API_KEY`, `ANTHROPIC_API_KEY`,
`RESEND_API_KEY`. Deploy knobs: `ANYA_JOB_DIR` (host job dir, default `./job`),
`ANYA_INTERVAL` (seconds, default 86400), `ANYA_PHASES`.

> **`op run` makes the build/pull progress look "fragmented."** To mask secrets, `op run`
> pipes the child's stdout/stderr instead of leaving it on your terminal. Compose sees a pipe,
> not a TTY, and falls back to its **plain** progress renderer — which prints every progress
> *event* on a new line instead of updating one in place. The result is hundreds of repeated
> lines like `Extracting 85B` / `Extracting 85B`. It's purely cosmetic: nothing is
> re-extracting, and the deploy is fine (confirm with `docker compose ps`). Options:
> - `--no-masking` — drop the pipe so Compose gets a real TTY and clean in-place bars. Safe
>   for `up -d`, which doesn't echo your secrets anyway. The simplest fix:
>   `op run --no-masking --env-file=.env -- docker compose up -d --build`
> - Keep masking but quiet the noise: add `--quiet-pull` (or `--progress quiet`) to the
>   `docker compose up` command.
>
> Note: the SSH `ControlMaster`/`ServerAliveInterval` settings in your `~/.ssh/config` are
> **not** the cause — multiplexing is the recommended setup for Docker-over-SSH and speeds up
> the many short sessions Compose opens.

## Deploy

The deploy ships the **job dir and data** (host content), then builds/runs the runtime image:

```bash
docker context use anya-droplet

# Put the curated content on the host (the image does NOT carry jobs/state):
rsync -a job/  root@<droplet-ip>:<path>/job/    # or maintain a curated dir on the host
rsync -a data/ root@<droplet-ip>:<path>/data/   # optional: carry over blotter/memory history

op run --env-file=.env -- docker compose up -d --build

# After an anya code/deps change, rebuild the runtime image:
op run --env-file=.env -- docker compose up -d --build anya
# After only a job change, no rebuild — just re-sync the job dir and restart:
rsync -a job/ root@<droplet-ip>:<path>/job/ && docker compose restart anya
```

A bind-mount source the remote daemon can't find is created **empty**, not errored — so if
you skip the job rsync, `anya serve` refuses to start (the fail-loud guard) and an absent
`data/` simply means "no history yet". Confirm both are populated before relying on a tick.

### Host dir ownership: the mounts must be writable by UID 10001

The container runs the worker as a **non-root user, `anya` (UID 10001)** — least privilege,
since it only ever writes under `/app/data` and the job dir. The Dockerfile `chown`s `/app`
to that user at *build* time, **but a bind mount shadows that**: when Compose mounts the
host's `./data` over `/app/data`, the host directory's ownership and permissions win, and the
build-time chown is irrelevant. So both mounted dirs must be writable by UID 10001 *on the
host*.

They usually aren't, because `rsync -a` preserves the **source** UIDs numerically — your
laptop user, not `10001` — so on the host `data/` and `job/` land owned by some unrelated UID.
The worker then can't even create its lock file, and every tick dies with:

```
PermissionError: [Errno 13] Permission denied: 'data/blotter.txt.lock'
```

Fix it with a throwaway **root** container — no need to SSH in or know the host path, and it
works even while the worker is crash-looping (overriding the entrypoint sidesteps both
`anya serve` and its empty-job-dir guard):

```bash
docker compose run --rm --user root --entrypoint chown anya -R 10001:10001 /app/data /app/job
docker compose restart anya
```

Equivalent host-side: SSH to the host and `chown -R 10001:10001` the actual `…/data` and
`…/job` directories. Re-apply after any step that recreates them with other ownership (a fresh
host, a new `ANYA_JOB_DIR`, or an rsync that resets ownership).

### Bringing down the containers

```sh
docker compose down anya
```

## Optional: crawl4ai for JS-heavy / bot-blocked fetches

Some jobs use the `crawl4ai` fetcher. It's a heavy image, kept behind a Compose profile:

```bash
op run --env-file=.env -- docker compose --profile crawl up -d --build
```

anya reaches it at `config.toml [fetch] crawl4ai_base_url` — set this to
`http://crawl4ai:11235` (the service name on the Compose network) in the baked or mounted
config. It has a healthcheck; if you want anya to wait for it to be healthy before starting,
add to the `anya` service:

```yaml
    depends_on:
      crawl4ai:
        condition: service_healthy
```

(Left out by default so the common, crawl-free deploy doesn't pull in the heavy image.)

## Persistence notes

Both bind mounts are host directories, so everything survives restarts **and** image
rebuilds (rebuilds only replace the runtime, never your content):

- **Process state** — `data/blotter.txt`, `data/memory.txt`, and the shared HTTP cache
  (`config.toml [paths]`, defaulting to `data/…` under the `/app` workdir) live under `./data`.
- **Per-job state** — anything a controller writes into its own job dir (e.g.
  `grant-hunter`'s `state.toml` seen-ledger + long-tail cursor) lives under the mounted
  job dir, so weekly-continuation state just works — no per-job mount gymnastics needed.

## Inspecting a running stack (from your laptop, remote context active)

```bash
docker ps                                   # containers on the Droplet
docker logs -f --tail 100 anya              # live tail of the scheduler
docker exec -it anya bash                   # shell in for ad-hoc poking
docker exec anya sh -c 'ls -la /app/data'   # wrap globs so they expand IN the container
docker compose run --rm anya run --select_jobs=grant-hunter --email_to=you@example.com
                                            # one-off run of a single job (bypasses frequency)
```

## Resetting a job's state (re-run from scratch)

To make a job re-process as if first-seen, clear its persisted state on the host (it lives in
the mounted job dir, so just delete the file and restart):

```bash
# wipe the seen-ledger / cursor (and optionally the HTTP cache to re-fetch pages):
rm -f job/grant-hunter/state.toml   # or $ANYA_JOB_DIR/grant-hunter/state.toml
rm -f data/http-cache.sqlite        # optional: also re-download instead of revalidating
docker restart anya
```

## Maintenance

Routine upkeep for the anya stack. Anything **host-wide** — disk hygiene that affects every
stack on the box, watching for upstream image updates, and supply-chain posture — lives in a
separate droplet-maintenance guide, because this droplet is shared with other stacks (e.g. the
Pulse Agent). Read that guide before running any prune or image-update command here: they act
on the **whole daemon**, not just anya.

### Disk: build cache from repeated rebuilds

Each `docker compose up --build` adds layers to the daemon's build cache; over many deploys
this dwarfs the images themselves. Diagnose, then reclaim:

```bash
docker system df                 # if "Build Cache" RECLAIMABLE is large, that's the culprit
docker builder prune -af         # reclaims build cache ONLY — safe on a shared host
```

> **Shared host, global blast radius.** `docker builder prune` touches only build cache and is
> safe. Do **not** reach for `docker system prune -a` (removes every image not tied to a
> *running* container — can delete another stack's images) or `--volumes` (can wipe named
> volumes other stacks depend on). anya's own content is bind-mounted host dirs, not named
> volumes, so a volume prune wouldn't lose anya data — but its neighbors might. The
> droplet-maintenance guide covers exactly what each prune touches.

### Updating anya

anya is built from local source, so an update is a rebuild — old `anya:latest` images become
dangling and are reclaimed by the prune above:

```bash
op run --env-file=.env -- docker compose up -d --build anya
```

### Updating crawl4ai

crawl4ai is an upstream image referenced by the **mutable** tag `unclecode/crawl4ai:basic` — a
tag that can change under you, with no signature or digest verification. Pull and restart it
deliberately, not automatically:

```bash
op run --env-file=.env -- docker compose --profile crawl pull crawl4ai
op run --env-file=.env -- docker compose --profile crawl up -d crawl4ai
```

For why you should pin this (and `anya`'s base) by **digest**, and how to get alerted when a
newer one ships, see the droplet-maintenance guide's supply-chain section.

### Health & liveness

```bash
docker ps                        # STATUS column shows healthy / unhealthy / starting
docker logs -f --tail 100 anya   # scheduler output; tick reports land here
```

anya's healthcheck is an **image-health** signal (imports cleanly, config parses) — it is *not*
a server liveness probe, since anya has no inbound port. A persistently `unhealthy` anya means
a broken build or config, not a hung request.

## Checklist

- [ ] Remote context created and `docker context use anya-droplet` selected.
- [ ] The job dir (`./job` or `$ANYA_JOB_DIR`) on the host holds exactly the jobs this host should run.
- [ ] Secrets come from `op run` / `bws run` / concrete `.env` — never committed, never baked.
- [ ] `./data` exists on the host (carry over blotter/memory if continuing).
- [ ] The host `data/` and job dirs are **owned by UID 10001** (the container's `anya` user) — `rsync` leaves them owned by your laptop UID, which the worker can't write to.
- [ ] crawl4ai started (`--profile crawl`) only if a curated job needs it.
- [ ] `docker logs -f anya` shows the scheduler started (or the fail-loud "no jobs" message if the mount is wrong) and the first tick ran clean.
