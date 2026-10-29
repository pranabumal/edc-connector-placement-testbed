# Runtime diagrams: catalog, negotiation, pull transfer through both Data Planes

Mermaid diagrams of what happens at runtime when a consumer gets data from the
provider in the distributed testbed, for the three provider placements
(Hybrid, Edge, Cloud) and the test cases TC1 to TC3. Every number in them comes
from one measured run per architecture (section 4); nothing is estimated.

The data path is source, provider Data Plane, consumer Data Plane, consumer
application. Stock EDC 0.14.1 does not route pulled data through the consumer's
Data Plane; the last hop is this testbed's own extension (section 8).

## 1. Files

| File | Content |
|---|---|
| `hybrid.mmd`, `edge.mmd`, `cloud.mmd` | One sequence diagram per architecture: TC1, TC2 and TC3 one after another, each with catalog fetch, contract negotiation and pull transfer, and a timing note per phase |
| `timing_overview.mmd` | Flowchart comparing the three architectures: time to first data per test case, one coloured arrow per test case |
| `split/<arch>_<tc>.mmd` | The same sequence diagrams, one test case each (9 files). The combined diagrams are about 2.5 times taller than wide, so at text width they do not fit one printed page; these do |
| `architecture/<arch>.svg` | Deployment (architecture) diagram of each placement: the servers with their specifications, the containers and ports on each, and the communication the tests exercise (section 7) |
| `timings.json` | Every timing the diagrams show, with the run it came from |
| `build_diagrams.py` | Generates all `.mmd` files and `timings.json` from the runs' `summary.json` |
| `build_architecture.py` | Generates `architecture/*.svg` from `timings.json` (no extra measurements) |
| `render.sh` | Renders every `.mmd` to `out/*.svg`, `out/*.pdf` and `out/*.png` (2x) |
| `render_architecture.sh` | Renders `architecture/*.svg` to `out/architecture/*.svg`, `.pdf` and `.png` (2x) with headless Chrome |
| `out/` | The rendered diagrams (`out/split/` for the per-test-case ones, `out/architecture/` for the architecture ones); not committed |

## 2. How to read the sequence diagrams

Participants, left to right, the same in all three diagrams and grouped by the host they run on:

| Participant | What it is | Host |
|---|---|---|
| Test runner | The test scripts, standing in for the consumer's application: catalog and negotiation calls come from `scripts/lib-edc.sh` (run by the test controller), the transfer and the fetches from `scripts/pull-client.py` (run on the consumer host) | Consumer, Contabo |
| Consumer CP | Consumer Control Plane (`consumer-cp`, management API and DSP) | Consumer, Contabo |
| Consumer DP | Consumer Data Plane (`consumer-dp`, pull proxy on port 9296) | Consumer, Contabo |
| Provider CP | Provider Control Plane (`provider-cp`) | Differs per architecture |
| Provider DP | Provider Data Plane (`provider-dp`, public endpoint) | Differs per architecture |
| Data source | `data-simulator` on TAU VM 2 | TAU VM 2 |

Each diagram has three sections in the same order, each in its own colour:
TC1 blue, TC2 green, TC3 orange. Every section runs the full flow with its own
catalog request and its own contract (one asset per test case):

1. **Catalog fetch.** The runner asks the consumer CP, which asks the provider CP over DSP and returns the catalog.
2. **Contract negotiation.** Contract request, agreement, verification, finalized (four DSP messages between the Control Planes). The runner polls the negotiation state every 0.1 s until FINALIZED.
3. **Data transfer, pull.**
   - *3a, setup (once):* the runner starts a transfer of type `HttpData-PULL`. The provider CP tells its Data Plane to start the flow; the Data Plane answers with its public endpoint and an access token; the provider CP sends both to the consumer CP in the transfer start message. The runner polls the consumer CP until the endpoint and token are available.
   - *3b, fetch (repeated, 30 times):* the runner sends a GET for the transfer to the consumer Data Plane, without a token. On the first fetch of a transfer the consumer Data Plane reads endpoint and token from its Control Plane. It then sends a GET with the token to the provider Data Plane, which checks the token, fetches the payload from the data source and returns it; the consumer Data Plane streams it back to the runner.

Notes carry the measured times. `Total TCn to first data` is the sum of catalog, negotiation, transfer setup and the first fetch: the time until the consumer holds its first piece of data. Every further fetch costs the median fetch time.

Two simplifications in the drawing:
- The polling loops run **concurrently** with the message exchange they wait for (the runner polls while the Control Planes exchange their messages). They are drawn after it for readability.
- A negotiation or transfer that EDC terminates is retried by the test scripts (up to 3 attempts). None occurred in these runs (`negotiation_retries` is 0 everywhere in `timings.json`), so no retry is drawn.

## 3. What differs between Hybrid, Edge and Cloud

The sequence of messages is **identical** in all three. Only the hosts and the network distances differ, which the host boxes and the "Network RTT" note at the top of each diagram show:

| | Provider CP | Provider DP | Provider CP to DP | Provider DP to source | Consumer to provider CP |
|---|---|---|---|---|---|
| Hybrid | cPouta | TAU VM 1 | 8 ms, WAN (start-flow signal and token cross it) | 3 ms | 46 ms |
| Edge | TAU VM 1 | TAU VM 1 | same host | 3 ms | 40 ms |
| Cloud | cPouta | cPouta | same host | 7 ms | 46 ms |

(RTT in ms, ping over Tailscale at the start of each run; see `timings.json`.) The consumer (Contabo) and the data source (TAU VM 2) are in the same place in every architecture.

## 4. Where the numbers come from

Runs of 13 October 2026 (EEST), test cases `pull-tc1`, `pull-tc2`, `pull-tc3`, 30 fetches each, with `PULL_VIA=consumer-dp`. The runs were made from the working copy that this commit records (the run metadata names the commit before it, `ba7baf8`, with uncommitted changes):

| Architecture | Run directory |
|---|---|
| Hybrid | `results/20261013T165021-hybrid-tuned-nosync/` |
| Edge | `results/20261013T171108-edge-tuned-nosync/` |
| Cloud | `results/20261013T172020-cloud-tuned-nosync/` |

Settings of all three runs (profile `tuned-nosync`):
- EDC transfer and data-plane wait 50 ms; negotiation wait 1000 ms (EDC's default).
- PostgreSQL `synchronous_commit=off` in all four connector databases. This is a diagnostic setting that takes the university VMs' slow disks out of the comparison; it is not a production setting.
- Every connector container limited to 4 CPU / 4 GB.
- Synthetic data from the simulator: TC1 272 B (control signal), TC2 9,640 B (sensor batch), TC3 473,603 B (video frame).

Definitions of the timings:

| Note in the diagram | Measurement |
|---|---|
| Catalog | Catalog request until the response arrives, timed by the test controller |
| Negotiation | Contract request until the agreement is FINALIZED, timed by the test controller (`negotiation_ms` minus the catalog time) |
| Transfer setup | Transfer request until endpoint and token are available on the consumer CP, timed on the consumer host |
| Fetch, median, first | One request to the consumer Data Plane until the last byte is back, timed on the consumer host. The first fetch also opens the connections and looks up the token; the median is over the later 29 |

To regenerate the diagrams from the run directories (the `results/` folder is git-ignored; `timings.json` keeps the numbers):

```
python3 diagrams/build_diagrams.py \
  --hybrid results/20261013T165021-hybrid-tuned-nosync \
  --edge   results/20261013T171108-edge-tuned-nosync \
  --cloud  results/20261013T172020-cloud-tuned-nosync
```

## 5. Limits to keep in mind

- **Single measurements.** Catalog and negotiation are measured once per test case per run, and negotiation in particular varies widely between runs (about 1.2 to 4.1 s in 170 earlier test negotiations at the same 1000 ms negotiation wait). Do not read differences between the three architectures in these notes as real. The fetch median over 30 fetches is much steadier.
- **Controller latency is inside Catalog and Negotiation.** The test controller (a Mac) issues those calls to the consumer CP over Tailscale; its round trip to Contabo measured 44 to 140 ms (mean 66 ms) and is part of every catalog and negotiation figure. Transfer setup and fetch are timed on the consumer host and do not contain it. The negotiation figure also contains up to 0.1 s of polling granularity.
- **TC1 includes warm-up.** TC1 is the first request after a fresh deployment, so its catalog (768 to 940 ms) and setup times are higher than TC2's and TC3's (about 290 to 360 ms for the catalog) in every architecture.
- **Equal hardware, not equal speed.** Each machine has 4 vCPU (the data source 2), but the CPU models differ.
- **No identity provider.** Both connectors use EDC's mock identity module, so there is no identity hub, wallet or credential exchange in the diagrams, and DSP messages carry no real identity tokens. Times are therefore a lower bound for a production dataspace.
- **No separate catalog service.** The catalog is the provider CP's own; there is no federated catalog.

## 6. Rendering

```
bash diagrams/render.sh
```

By default this runs `npx -y @mermaid-js/mermaid-cli` and needs Node.js 18 or newer. The files in `out/` were rendered with the Mermaid CLI 12.0.0 on Node 22 and the installed Google Chrome, using

```
MMDC=<path to mmdc> PUPPETEER_CONFIG=<json> bash diagrams/render.sh
# {"executablePath": "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
#  "args": ["--no-sandbox"], "headless": "shell"}
```

`.pdf` and `.svg` are vector files for LaTeX; `.png` is rendered at 2x scale.
Box labels contain no parentheses on purpose: Mermaid 12 reads them as part of the colour value.

## 7. Architecture diagrams

`architecture/hybrid.svg`, `edge.svg` and `cloud.svg` show where everything runs
in each placement. They are drawn directly as SVG on a fixed grid, not with
Mermaid, because Mermaid's automatic layout of nested boxes made the figure
about twice as tall as wide and let arrows cross text. The figure is 1660 x 1334
px, landscape, and fits one printed page.

What they show:
- **Servers** as coloured boxes in the order of the data path (test controller, consumer, provider, data source), each with its specification: CPU, RAM, operating system, Docker version, and the time of one synchronous database write (the storage figure that explained the Edge results). IP addresses are left out on purpose.
- **Containers and ports** on each server: the four connector units with their own PostgreSQL databases, the pull client, the simulator and the AAS. Greyed boxes are deployed but not used by the pull tests (receiver, AAS).
- **Hybrid** puts the provider Control Plane (cPouta) and Data Plane (TAU VM 1) in separate boxes, so the one remote hop inside the provider, link (3), is visible; Edge and Cloud keep both in one box.
- **Communication tested**: numbered arrows (1) to (8) with protocol, port and measured round trip time. Thick arrows are on the timed path, dotted ones are not timed. The legend maps the arrows to the phases of the sequence diagrams: catalog (1)(2), negotiation (1)(2), transfer setup (4)(2)(3)(2), fetch (5)(7)(8), and on the first fetch of a transfer also (6).

The server specifications were read from the machines themselves on 2 to 13 October 2026; the round trip times are those in `timings.json` (same runs as the sequence diagrams); (1) is the mean of 10 pings from the test controller to Contabo.

```
python3 diagrams/build_architecture.py     # writes architecture/*.svg
bash diagrams/render_architecture.sh       # writes out/architecture/*.{svg,pdf,png}
```

## 8. The consumer Data Plane on the data path

In stock EDC 0.14.1 only the provider's Data Plane moves data. In a pull the
consumer's Control Plane receives the provider Data Plane's endpoint and an
access token, and whoever holds them fetches from the provider's Data Plane
directly. A consumer-side Data Plane is only ever asked to prepare a
destination (`DataPlaneManager.provision`); EDC's own HTTP proxy module
(`data-plane-public-api-v2`) is deprecated with the note to provide an
alternative implementation.

This testbed adds that implementation to its Data Plane runtime
(`mvd/dp-runtime/.../proxy/ConsumerPullProxyExtension`), after the model of
Tractus-X EDC's `edc-dataplane-proxy-consumer-api`: `GET :9296/proxy/<transfer id>`
on the consumer's Data Plane reads endpoint and token from the consumer's
Control Plane (once per transfer), fetches from the provider's Data Plane
through EDC's transfer pipeline and streams the data back. The consumer's
application never holds the token.

`PULL_VIA=direct` runs the stock path instead (the client fetches from the
provider's Data Plane with the token). Same Hybrid deployment, 13 October 2026,
median of 29 fetches:

| | Through the consumer Data Plane | Direct (stock EDC) | Extra hop |
|---|---|---|---|
| TC1, 272 B | 80.7 ms | 58.9 ms | +21.8 ms |
| TC2, 9,640 B | 76.4 ms | 69.5 ms | +6.9 ms |
| TC3, 473,603 B | 314.9 ms | 280.7 ms | +34.2 ms |

One run each (`results/20261013T165021-hybrid-tuned-nosync/`,
`results/20261013T165653-hybrid-direct-tuned-nosync/`), so the size of the
extra hop is indicative only. A contract valid for 30 s still cuts access off
through this path: the first refused fetch came 0.27 s after expiry
(`results/20261013T170304-hybrid-timed-tuned-nosync/`).
