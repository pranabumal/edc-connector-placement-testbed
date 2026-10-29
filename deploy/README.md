# Distributed deployment

The dataspace split into independently deployable **units**, so the provider's
Control Plane and Data Plane can run on different machines (thesis §3.3).

| Unit | Containers | Own database holds |
|---|---|---|
| `provider-source` | simulator, basyx-aas, basyx-mongo, crane-adapter | — (the factory's data source, not a connector) |
| `provider-cp` | provider-cp, provider-cp-db | assets, policies, contract definitions, negotiations, agreements, transfer processes, registered data planes |
| `provider-dp` | provider-dp, provider-dp-db | data flows, access tokens |
| `consumer-cp` | consumer-cp, consumer-cp-db | negotiations, agreements, transfer processes, EDRs, registered data planes |
| `consumer-dp` | consumer-dp, consumer-dp-db, receiver | data flows, access tokens |
| `dashboard` | ui-api, ui-provider, ui-consumer | test-run history (SQLite) |

Naming: `{participant}-{plane}` for the connector, `{unit}-db` for its
Postgres, `{participant}_{plane}` for the database name. Databases are never
published on the host; only their own connector reaches them.

Units talk to each other only through **host addresses and published ports** —
never through a shared Docker network — so the same wiring works whether two
units share a machine or sit on different clouds.

## Roles and architectures

`deploy/hosts.env` names one machine per **role**:

| Role | Meaning | Runs |
|---|---|---|
| `EDGE_HOST` | factory edge server | provider CP and/or DP when the architecture puts them at the edge |
| `SOURCE_HOST` | factory data source ("the machine") | `provider-source`, in every architecture |
| `CLOUD_HOST` | provider cloud | provider CP and/or DP when the architecture puts them in the cloud |
| `CONSUMER_HOST` | external partner | `consumer-cp`, `consumer-dp` (+ receiver), in every architecture |

Only the provider's planes move (`deploy/arch/<arch>.env`):

| `<arch>` | provider-cp | provider-dp | data source | consumer |
|---|---|---|---|---|
| `edge` | edge | edge | source | consumer |
| `hybrid` | cloud | edge | source | consumer |
| `cloud` | cloud | cloud | source | consumer |

The Data Plane always fetches from `SOURCE_HOST`, so in `cloud` the data really
crosses the factory → cloud link. Per-role resource limits (`EDGE_*`,
`CLOUD_*`, `CONSUMER_*`) apply to each connector container.

## Usage

```bash
# once: same file on every machine
cp deploy/hosts.env.example deploy/hosts.env   # fill in the four roles

# on each machine, same <arch> — the machine's roles are detected from its IPs
deploy/deploy.sh hybrid

# then, from the machine running the tests
bash scripts/1-setup-provider.sh       # safe to re-run
bash scripts/2-tc1-realtime-control.sh
```

- **Switch architecture:** run `deploy.sh <new-arch>` on every machine. Units
  that no longer belong on a machine are stopped (data kept). Each machine has
  its own `provider-cp-db`, so re-run `1-setup-provider.sh` after provider-cp
  moves.
- **Explicit roles:** `deploy.sh hybrid --on edge,source` if auto-detection
  can't match the machine (e.g. roles given as public DNS names).
- **Single machine, same wiring:** `deploy.sh hybrid --local` runs every role
  here, addressed by this machine's IP.
- **Stop:** `deploy.sh <arch> down`; add `--wipe` to also delete databases.
- **Status:** `deploy.sh <arch> ps`.

Ports are published on each role's own address (with Tailscale IPs: only on
the Tailscale interface). Override per role with `EDGE_BIND=` etc.

`deploy.sh` writes `deploy/.endpoints.env` (the resolved address of each unit),
which `scripts/lib-endpoints.sh` loads. Without it, the scripts fall back to the
single-machine stack in `docker/docker-compose.yaml`, which still works as
before. The two can't run on one machine at the same time (same container
names and ports).

Files that stay on each machine and are git-ignored: `hosts.env`,
`secrets.env` (DB password, generated on first run), `.endpoints.env`.
