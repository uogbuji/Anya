---
name: docker-compose-deploy
description: Deploy a multi-service stack to a single host (e.g. a DigitalOcean Droplet) with Docker Compose over a remote Docker context — startup ordering & healthchecks, read-only mounts and fail-loud state, reverse-proxy ingress, one-shot init/seed services, runtime secret injection, and inspecting a running stack. Use when writing or reviewing a compose.yml for deployment, wiring service dependencies, or debugging a deploy.
---

# Docker Compose deployment (single host / Droplet)

## Purpose
Ship a multi-container stack to one host with `docker compose`, with no CI/CD pipeline
required: you build locally and run the containers on a remote host via a **remote Docker
context**. The deploy is a single command. This skill captures the wiring that makes that
reliable — startup ordering, healthchecks, mounts, ingress, and secrets — plus the
hard-won gotchas.

Complements [python-backend](../python/SKILL.md) (the service code) and
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
- **Content that must exist before a container starts cannot be bind-mounted** — Docker
  will just make an empty dir. Bake such content into the image with `COPY` instead (and
  rebuild to update it).

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
  read-only-SQLite note in [python-backend](../python/SKILL.md).

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
- Persist auto-provisioned certs in a volume so they survive restarts.
- Requires a DNS A record at the host and ports 80/443 reachable.

## Per-service environment (least privilege)
Pass each service only the env it needs. A read-only query service needs the read creds
(e.g. a Slack token, a ClickUp key) but **not** the write-side secrets (webhook signing
secrets, LLM keys). Trimming the surface limits blast radius if one container is
compromised and makes each service's dependencies legible.

## Persistence
Keep all persistent data in bind mounts under one gitignored dir (`./data/…`), one
subdir per concern (app state, certs, caches). It's customer-sensitive — never commit it.
Pre-create the dirs (an init script or `start.sh`) so Docker doesn't create them
root-owned on first run.

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

## Checklist
- Deploy is one non-interactive command (context + secrets wrapper + `compose up --build`).
- Dependents that rely on a dependency's *startup work* gate on `service_healthy` (with a
  real healthcheck), not `service_started`.
- Healthchecks use an in-image tool (e.g. `python -c …`) on slim images, not curl/wget.
- One-shot init/seed runs as a container, gated by `service_completed_successfully`.
- Read-only consumers mount state `:ro`; a missing required mount fails loud, never
  silently empty.
- Pre-start content is `COPY`'d into the image, not bind-mounted (remote-context limitation).
- Ingress is a stable hostname behind a TLS reverse proxy; certs persisted.
- Each service gets only the env/secrets it needs.
- Secrets injected at runtime via `op run` / `bws run`; never baked into images or committed.

## References
- [python-backend](../python/SKILL.md) — service code, async hardening, read-only SQLite.
- [testing](../testing/SKILL.md) — keep the fail-loud behaviour under test.
- Compose `depends_on` conditions: <https://docs.docker.com/compose/how-tos/startup-order/>
- Compose healthcheck: <https://docs.docker.com/reference/compose-file/services/#healthcheck>
