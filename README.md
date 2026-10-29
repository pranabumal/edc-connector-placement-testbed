# EDC Connector Placement Testbed

Testbed, measurement scripts and analysis for the master's thesis

> Pranab Sarker, *Deploying Data Space Connectors on the Cloud Continuum for Manufacturing*,
> MSc thesis, Tampere University, 2026.

The thesis measures where the Control Plane (CP) and Data Plane (DP) of an
Eclipse Dataspace Components (EDC) 0.14.1 provider connector should run on the
cloud continuum. It compares three placements — **Cloud**, **Edge** and
**Hybrid** (CP in the cloud, DP at the edge) — on three manufacturing data flows
(TC1 real-time control, TC2 high-frequency sensor data, TC3 large payloads),
with both HttpData-PUSH and HttpData-PULL transfers.

## Contents

| Folder | What it holds |
| --- | --- |
| `mvd/` | The connector runtimes: `cp-runtime` (Control Plane), `dp-runtime` (Data Plane) and the shared extensions in `mvd-connector` |
| `docker/` | Dockerfiles of the connectors, the data source simulator, the receiver and the dashboard; `docker-compose.yaml` runs everything on one machine |
| `deploy/` | Distributed deployment: one unit per connector plane, placements in `deploy/arch/`, timing profiles in `deploy/timing/` (see `deploy/README.md`) |
| `scripts/` | Provider setup, the test cases TC1–TC4, the pull client, the link-cut test and the driver of a measurement set (`run-measurement-set.sh`) |
| `analysis/` | Statistics and every figure and table of the results chapter |
| `diagrams/` | Architecture and sequence figures of the thesis (SVG, rendered to PDF) |

## Regenerating the results

Needs only this repository and the data archive attached to the release
`thesis-final`, not the testbed:

```bash
git checkout thesis-final
# unpack the release archive into results/
python3 -m venv analysis/.venv && . analysis/.venv/bin/activate
pip install -r analysis/requirements.txt
python analysis/rq1.py && python analysis/rq2.py && python analysis/rq3.py
python analysis/perf_models.py && python analysis/review_rerun.py && python analysis/repeats_BD.py
python analysis/spread.py && python analysis/fig_simple.py     # need the output of rq1.py
```

Figure PDFs go to `figures/images/`; tables, numbers (JSON) and PNG previews to
`analysis/out/`.

Every bootstrap uses a fixed seed, so the numbers are identical on every run.
Appendix B of the thesis lists which script produces which figure or table.

## Repeating the measurements

Needs four machines in the roles edge, source, cloud and consumer:

```bash
cp deploy/hosts.env.example deploy/hosts.env   # name the machine of each role
scripts/run-measurement-set.sh <set> [placement]
```

`deploy/README.md` describes the preparation of the machines. New measurements
will differ from the archived ones in network paths and load, so they test the
conclusions rather than the exact numbers.

## Provenance and credits

The connector code builds on the
[Eclipse Dataspace Components Samples](https://github.com/eclipse-edc/Samples)
(Apache License 2.0, see `NOTICE.md`). The first two-connector setup that this
testbed grew from was prepared by Benedict Homuth (Fraunhofer ISST) and Krista
Mätäsniemi (Tampere University). The distributed deployment, the test cases,
the measurement tooling and the analysis were written for the thesis.
`PROVENANCE.md` explains how the commits recorded by the measurement runs relate
to this repository.

## Licence

Apache License 2.0, see `LICENSE`.
