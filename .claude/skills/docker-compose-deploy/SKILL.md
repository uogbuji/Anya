---
name: docker-compose-deploy
description: Use when writing or reviewing a compose.yml for deployment, wiring service dependencies, or debugging a deploy to a single host (e.g. a DigitalOcean Droplet) over a remote Docker context. Covers healthchecks and startup order, read-only mounts, ingress and port exposure, digest pinning, non-root containers, init services, runtime secrets, and backups.
---

# Docker Compose deployment (single host / Droplet)

## Purpose
Ship a multi-container stack to one host with `docker compose`, with no CI/CD pipeline
required: you build locally and run the containers on a remote host via a **remote Docker
context**. The deploy is a single command. This skill captures the wiring that makes that
reliable — startup ordering, healthchecks, mounts, ingress, and secrets — plus the
hard-won gotchas.

Complements [python-backend](../python-backend/SKILL.md) (the service code) and
[testing](../testing/SKILL.md).

## The deploy model
- **One command, no pipeline.** `docker compose --build up -d` builds images on your
  machine, ships layers over SSH to the host's Docker daemon, and (re)starts services.
- **Same `compose.yml` locally and in prod.** Use Compose *profiles* to scope which
  services run where (e.g. a `prod`/`ingest` profile that pulls in the public-facing
  services on top of the always-on ones).
- **Secrets injected at runtime, never baked into images.** Wrap the deploy in a secrets
  manager: `op run --env-file=.env -- docker compose …` (1Password) or
  `bws run -- docker compose …` (Bitwarden). The `.env` holds `op://…` / reference URIs;
  the wrapper resolves them for the child process only.

  **Gotcha:** `op run --env-file=.env -- foo "$SECRET"` passes an *empty* `$SECRET` — your
  outer shell expands it before `op` injects anything. Push the expansion into the injected
  env: `op run --env-file=.env -- sh -c 'foo "$SECRET"'`.

```bash
docker context use <host-context>          # target the remote host (setup below)
op run --env-file=.env -- docker compose --profile prod up -d --build
# rebuild just one service after a code change:
op run --env-file=.env -- docker compose --profile prod up -d --build <service>
```

## Remote Docker context (one-time)
```bash
docker context create <host-context> --docker "host=ssh://root@<host-ip>"
docker context use <host-context>          # all docker/compose cmds now target the host
docker context use default                 # switch back to local
```
Use key-based SSH as a non-interactive user; never set a root password to "expedite"
access. Verify with `docker context show` and `docker ps` (should list the host's
containers).

### Bind mounts over a remote context — the gotcha
Compose resolves a relative volume path (`./data/x`) to an **absolute local path** and
sends *that* to the remote daemon, which **silently creates an empty directory** there if
it doesn't exist. Consequences:
- Fine for `data/` dirs that services populate at runtime.
- **Pre-existing content bind-mounts correctly only if the project sits at the *same
  absolute path* on both machines**, because the path string is computed locally. `./kb`
  run from `/home/me/app` mounts the host's `/home/me/app/kb`, not `/srv/app/kb`; if that
  doesn't exist on the host you get an empty dir (and e.g. a seed step silently seeds
  nothing). Two fixes: run `docker compose` **on the host** so `./x` is host-local (you then
  need secrets present there — `op`/`bws` or an injected env file), or **keep the repo at an
  identical absolute path** on both machines.
- `COPY`-into-image works only for content **identical across every deploy**. Content that
  varies per host/tenant (a config/KG/`kb-reference` dir, especially for an org-agnostic
  image) must use one of the above — baking it in defeats the point.
- Symptom: a container sees an **empty** mount that's clearly populated on the host → this
  path mismatch, not a missing rsync.

## Pin third-party images by digest
Mutable tags (`:latest`, `:basic`, `:4`) drift: the registry can repoint a tag at a new
build between deploys, so what you ran yesterday isn't what you run today — and a compromised
or broken upstream lands on your next `up`. Pin the **digest** and keep the tag only as a
human label:

```yaml
image: unclecode/crawl4ai:basic@sha256:<digest>   # tag = label, digest = contract
```
- Find the digest without pulling: `docker buildx imagetools inspect <ref>` (or, once pulled,
  `docker inspect --format '{{index .RepoDigests 0}}' <ref>`).
- To make updates deliberate instead of silent, run an image-update *notifier* (e.g.
  [diun](https://crazymax.dev/diun/)) that **alerts** on a digest move rather than
  auto-updating — a human re-pins and redeploys. If a notifier needs the Docker socket, mount
  it read-only (`/var/run/docker.sock:/var/run/docker.sock:ro`) and pin the notifier's own
  image too.
- Prefer official images / known publishers and watch for typosquatted namespaces. Images you
  build on the host (the model above) don't need pinning — you control the bytes.

## Startup ordering & healthchecks
`depends_on` has two conditions, and the difference is the single most common deploy bug:

- `condition: service_started` — waits only for the dependency's **process to launch**.
- `condition: service_healthy` — waits for its **healthcheck to pass**.

**If a service does real work during startup that a dependent relies on (creates a DB,
runs migrations, seeds a cache, binds a socket), the dependent must gate on
`service_healthy`, not `service_started`.** Otherwise it races that work and crash-loops
on a cold boot (recovering only because `restart: unless-stopped` keeps retrying — noisy
and slow, and it returns errors in the gap).

```yaml
services:
  api:
    # An ASGI/HTTP app only answers routes AFTER its lifespan/startup completes, so a
    # 200 from a cheap /healthz is a reliable "startup work is done" signal. Slim images
    # have no curl/wget — use the interpreter you already have:
    healthcheck:
      test: ['CMD', 'python', '-c',
             "import urllib.request; urllib.request.urlopen('http://localhost:8080/healthz')"]
      interval: 5s
      timeout: 3s
      retries: 12
      start_period: 5s
  reader:
    depends_on:
      api:
        condition: service_healthy   # not service_started — api creates state reader reads
```

- Put the healthcheck on the service whose readiness *means something* (here, the one
  that creates the shared state), and gate dependents on it.
- `urlopen` exits non-zero on connection-refused or a non-2xx status → Docker reads that
  as unhealthy and retries until `start_period` + `interval × retries` elapses.

## One-shot init / seed services
Run setup work as its own service that exits, and gate the app on its **success**:

```yaml
  seed:
    command: ['myapp', 'seed']
    restart: 'no'
  app:
    depends_on:
      seed:
        condition: service_completed_successfully
```
Run init *in a container* (reusing the app image) rather than a host script, so it can't
be silently skipped and doesn't depend on host tooling.

**On Compose v5.3.0+ (what a current Droplet runs), prefer native `pre_start` init
containers when the setup belongs to *one* service** — no separate service, no
`depends_on` wiring:

```yaml
  app:
    image: myapp:latest
    pre_start:
      - command: ['myapp', 'seed']   # own ephemeral container; defaults to the service image
```
Each step runs to completion in its own ephemeral container after the service container is
created but before it starts; a non-zero exit aborts the service *and* its dependents. Steps
share the service's mounts and networks, and — like the seed above — are **skipped on later
`up`s if they succeeded and their definition is unchanged** (rerun with `--force-recreate`).
Keep the separate one-shot service + `service_completed_successfully` when the init is
**shared by several services** (it runs once; each dependent gates on it) or you must support
pre-5.3 hosts — `pre_start` is per-service, so N services each declaring it run it N times.

## Read-only mounts & fail-loud state
- Mount state a service only *reads* as read-only: `- ./data/state:/data/state:ro`. It
  documents intent and prevents accidental writes (least privilege for the filesystem).
- **A missing required mount must fail loudly, not silently degrade.** Many libraries
  *auto-create* on open (SQLite makes an empty DB; a dir mount appears as empty), so a
  forgotten/misconfigured mount masquerades as "no data" — a trust-destroying false
  negative for users. On startup, verify required state exists and **refuse to start** if
  not (so deploy/monitoring catches it); at request time, distinguish "present but empty"
  (a benign finding) from "unavailable" (a surfaced system error). For SQLite specifically,
  open `mode=ro` so a missing file errors instead of being auto-created — see the
  read-only-SQLite note in [python-backend](../python-backend/SKILL.md).

## Run containers as non-root
A container with no `USER` runs as **root**, and root in the container is root on every
writable bind mount — and a stronger foothold for any escape. Add a non-root `USER` in the
Dockerfile wherever the image allows it (e.g. a uid like `10001`), and have the app own only
the dirs it must write. Identity, filesystem (`:ro` mounts, above), and network (internal-only
services, below) least-privilege are **independent layers** — apply all three; one doesn't
substitute for another.

## Reverse-proxy ingress
Terminate TLS and route at a reverse proxy (e.g. Caddy) on a **stable hostname**, so
external webhook/callback URLs don't churn across rebuilds.

```caddyfile
app.example.com {
  # More-specific matchers win regardless of order, so a path can be peeled off to a
  # second service while everything else falls through to the default upstream.
  @reads path /api/reads/*
  reverse_proxy @reads reader:8081
  reverse_proxy api:8080
}
```
- A fixed hostname → stable Slack/Fireflies/webhook request URLs (only change them if you
  change the host).
- Persist auto-provisioned certs in a volume so they survive restarts. If the cert dir's
  path *changes* (you move the project, or a bind mount now resolves elsewhere per the
  remote-context rule above), the proxy starts with an **empty cert store and re-issues** —
  burning Let's Encrypt rate limits. Carry the cert dir across moves.
- Requires a DNS A record at the host and ports 80/443 reachable.
- **Only the proxy publishes a *public* port.** Every other service stays on the internal
  compose network and is reached by service name (`reader:8081`, `searxng:8080`) — it needs no
  `ports:` entry at all. A published `8081:8080` binds on **all** host interfaces: a public
  door on the host (firewall permitting), not just localhost. If you expose a port purely for
  local-dev convenience, bind it to loopback — `127.0.0.1:8081:8080` — so it's reachable only
  from the host itself (or an SSH tunnel), never the internet. Widening it back to `8081:8080`
  silently reopens that door, so call it out in review.

## Per-service environment (least privilege)
Pass each service only the env it needs. A read-only query service needs the read creds
(e.g. a Slack token, a ClickUp key) but **not** the write-side secrets (webhook signing
secrets, LLM keys). Trimming the surface limits blast radius if one container is
compromised and makes each service's dependencies legible.

## Secrets & env values containing `$` (interpolation)
A value with a literal `$` — a bcrypt hash (`$2a$14$…`), some generated passwords, a
connection string — gets **silently mangled** by Compose's variable interpolation: it
presents as a config that "looks right" while the container receives garbage, and a
downstream parser (Caddy `basic_auth`, a DB driver) then rejects it.

- **Compose interpolates values loaded from the auto `.env` and `env_file`** (unquoted *and*
  double-quoted), so a `$` before a digit or underscore is silently dropped — a bcrypt hash
  `$2a$14$…` came through as `a4` (observed on Compose v5.1.3).
- **Treat this empirically, not from a version or a bug ticket.** dotenv `$`-handling has
  been reworked repeatedly across Compose releases, so any rule pinned to "fixed in X" /
  "broken in Y" ages out — rely on the fixes below and on verifying the result. (`$$`
  escaping is a `compose.yaml` mechanism, not a reliable dotenv escape — don't count on it
  there.)
- **Verify with `docker inspect`, never `docker compose config`** — `config` re-escapes a
  literal `$` as `$$`, so a *correct* value looks doubled. Trust the container's actual env
  over docs or memory:
  `docker inspect <container> --format '{{range .Config.Env}}{{println .}}{{end}}' | grep VAR`

Reliable fixes, best first:
1. **Keep the secret in the manager and inject via `op run`/`bws run`** — the `$` never
   touches a dotenv parser. Store the raw hash as a field, reference it as `op://…` in
   `.env`. (Preferred: it's a credential anyway.)
2. **`env_file:` on the service**, not an interpolated `environment: - VAR`. Caveat:
   `environment:` *overrides* `env_file:`, so remove the var from `environment:` when you
   move it; and single-quote it in the file (`REPORT_HASH='$2a$14$…'`), since recent Compose
   interpolates unquoted `env_file` values too.
3. **Shell-export it** just before `up` (`export REPORT_HASH='$2a$14$…'`) — single-quotes are
   literal and the shell env wins over `.env` for a bare `- VAR`. Per-shell only.

A value that fails to parse can take down more than its own service: a reverse proxy that
can't load one directive **refuses its whole config and exits**, so every route behind it
goes dark (see the debugging note under Inspecting a running stack).

## Persistence
Keep all persistent data in bind mounts under one gitignored dir (`./data/…`), one
subdir per concern (app state, certs, caches). It's customer-sensitive — never commit it.
Pre-create the dirs (an init script or `start.sh`) so Docker doesn't create them
root-owned on first run.

**Bind mounts are not a backup.** `prune` — even `--volumes` — can't touch a bind mount, but
a disk loss or a stray `rm` can. (That's also the asymmetry vs. named volumes: bind mounts
survive volume prune; named volumes don't.) If the data is customer-sensitive and not
reproducible, give `./data/` a real backup/restore story, separate from the host.

## Inspecting a running stack (from your laptop)
With the remote context active, all of these target the host:
```bash
docker ps                                  # running containers on the host
docker logs -f --tail 100 <container>      # live tail
docker logs <one-shot> | grep <done-marker># confirm a seed/init finished
docker exec -it <container> bash           # shell in for ad-hoc investigation
```
**`docker exec` glob gotcha:** a glob like `ls data/x/*.md` is expanded by your **local**
shell against your local files, then those names are sent to the container (which may not
have them). Wrap globs to expand inside the container: `docker exec <c> sh -c 'ls data/x/*.md'`.

**When "everything" is unreachable, suspect the edge, not the app.** A generic client-side
error (a Slack `dispatch_unknown_error`, a bare 502) usually means the request never reached
the service. Check in order: (1) the reverse proxy's own logs — it *exits* on a config error,
taking all routing with it; (2) whether the app logged the request at all — no access-log
line means it never arrived. A healthy app with no incoming request = an ingress problem
(proxy down, bad config, missing/expired cert), not an app bug.

## Sharing the host with other stacks
One host means one Docker daemon, so maintenance is **global** — a prune or image pull issued
for one stack acts on *every* stack on the host. The one piece that's specific to this skill's
build-on-host model: each `--build` accrues **build cache**, so reclaim it with `docker builder
prune -af` (safe — it touches nothing any stack runs), never `docker system prune -a`, which
also deletes images a *stopped* sibling stack (e.g. an exited one-shot seed/init service) still
needs.

Broader host-level upkeep — disk-prune policy, watching for upstream image updates, supply-chain
posture, and a per-stack inbound/storage/uid inventory — is cross-stack, so it lives in a
companion host-maintenance runbook (a `DROPLET_MAINTENANCE.md`-style doc), not in this per-stack
skill.

## Checklist
- Deploy is one non-interactive command (context + secrets wrapper + `compose up --build`).
- Third-party images pinned by digest (tag = label); an update notifier watches for drift.
- Containers run as a non-root `USER` wherever the image allows.
- Dependents that rely on a dependency's *startup work* gate on `service_healthy` (with a
  real healthcheck), not `service_started`.
- Healthchecks use an in-image tool (e.g. `python -c …`) on slim images, not curl/wget.
- Init/seed runs in a container: `pre_start` (v5.3.0+, per-service) or a separate service
  gated by `service_completed_successfully` (shared init / pre-5.3 hosts).
- Read-only consumers mount state `:ro`; a missing required mount fails loud, never
  silently empty.
- Pre-existing bind-mount content resolves (same absolute path on both machines, or
  `compose` run on the host); `COPY` only for content identical across every deploy.
- Ingress is a stable hostname behind a TLS reverse proxy; certs persisted.
- Only the reverse proxy publishes a *public* port; any dev-only port is bound to `127.0.0.1`.
- Each service gets only the env/secrets it needs.
- Secrets injected at runtime via `op run` / `bws run`; never baked into images or committed.
- Values containing `$` use `op`/`bws` or `env_file:` (single-quoted), never a bare
  interpolated `environment: - VAR`; verified via `docker inspect`, not `compose config`.
- Env-only change? `up -d --force-recreate <svc>` — a plain `up -d` may not recreate.
- Bind-mount state has a backup/restore story (prune won't delete it; disk loss will).
- On a shared host, reclaim with `docker builder prune -af`; never `system prune -a`/`--volumes` blind.

## References
- [python-backend](../python-backend/SKILL.md) — service code, async hardening, read-only SQLite.
- [testing](../testing/SKILL.md) — keep the fail-loud behaviour under test.
- Compose `depends_on` conditions: <https://docs.docker.com/compose/how-tos/startup-order/>
- Compose `pre_start` init containers (v5.3.0+): <https://docs.docker.com/compose/how-tos/init-containers/>
- Compose healthcheck: <https://docs.docker.com/reference/compose-file/services/#healthcheck>
- Compose `ports` short syntax (the `127.0.0.1:` host-IP form): <https://docs.docker.com/reference/compose-file/services/#ports>
- Compose variable interpolation (dotenv `$` handling): <https://docs.docker.com/reference/compose-file/interpolation/>
- diun (Docker Image Update Notifier): <https://crazymax.dev/diun/>
