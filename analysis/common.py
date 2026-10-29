"""
common.py — shared by the thesis analysis scripts (rq1.py, rq2.py, rq3.py).

Phase 2 of the thesis plan: every result figure and table is generated from
the archived runs of the 22 October 2026 campaign, so it can be regenerated.

  RUNS       the valid runs per measurement set (results/RUN_REGISTER-20261022.md)
  load(tag)  summary.json of a run; raw(tag, name) any JSON file in its directory
  boot_ci    bootstrap confidence interval of the median (Efron 1979)
  mwu        two-sided Mann–Whitney U test (Mann & Whitney 1947)
  savefig    PDF into the thesis (images/results/) and PNG for review
  write_table LaTeX table body into analysis/out/tables/

Run with analysis/.venv/bin/python (see analysis/requirements.txt).
"""
import json
import os
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy import stats

REPO = Path(__file__).resolve().parents[1]
RESULTS = REPO / "results"
# Figures go into the thesis sources when they sit next to this repository (or
# THESIS_DIR names them); otherwise into figures/ of this repository.
_thesis = Path(os.environ.get("THESIS_DIR", REPO.parent / "Thesis Writing TAU"))
THESIS = _thesis if _thesis.is_dir() else REPO / "figures"
FIG_DIR = THESIS / "images" / "results"          # PDFs \includegraphics'd by the thesis
OUT = REPO / "analysis" / "out"                   # PNG previews, tables, numbers
for d in (FIG_DIR, OUT / "png", OUT / "tables"):
    d.mkdir(parents=True, exist_ok=True)

PLACEMENTS = ["hybrid", "edge", "cloud"]
LABEL = {"hybrid": "Hybrid", "edge": "Edge", "cloud": "Cloud", "source": "No EDC (baseline)"}
# Okabe–Ito colour-blind-safe palette; baseline grey
COLOR = {"hybrid": "#0072B2", "edge": "#E69F00", "cloud": "#009E73", "source": "#7F7F7F"}
TCS = ["tc1", "tc2", "tc3"]
TC_LABEL = {"tc1": "TC1 control\n(272 B)", "tc2": "TC2 sensor batch\n(9,640 B)", "tc3": "TC3 large payload\n(473,603 B)"}
TC_SHORT = {"tc1": "TC1", "tc2": "TC2", "tc3": "TC3"}
# target rate (Hz) and deadline (ms) of the pull schedule (Set B)
TARGET = {"tc1": (50, 20.0), "tc2": (1, 1000.0), "tc3": (24, 1000 / 24)}

# Valid runs of the campaign, from results/RUN_REGISTER-20261022.md.
RUNS = {
    "A": {  # push, 20 transfers per TC, tuned-nosync; three repeats per placement
        ("hybrid", 1): "20261022T135703-hybrid-tuned-nosync-A-r1",
        ("hybrid", 2): "20261022T151821-hybrid-tuned-nosync-A-r2",
        ("hybrid", 3): "20261022T153544-hybrid-tuned-nosync-A-r3",
        ("edge", 1): "20261022T150859-edge-tuned-nosync-A-r1",
        ("edge", 2): "20261022T142409-edge-tuned-nosync-A-r2",
        ("edge", 3): "20261022T154506-edge-tuned-nosync-A-r3",
        ("cloud", 1): "20261022T141426-cloud-tuned-nosync-A-r1",
        ("cloud", 2): "20261022T143257-cloud-tuned-nosync-A-r2",
        ("cloud", 3): "20261022T152653-cloud-tuned-nosync-A-r3",
    },
    "B": {  # pull on a fixed schedule, 300 s per TC; seq = 1 worker, par = 4, src = no-EDC baseline
        ("hybrid", "seq"): "20261022T155413-hybrid-tuned-nosync-B-seq",
        ("hybrid", "par"): "20261022T161509-hybrid-tuned-nosync-B-par",
        ("hybrid", "src"): "20261022T163606-hybrid-tuned-nosync-B-src",
        ("edge", "seq"): "20261022T165923-edge-tuned-nosync-B-seq",
        ("edge", "par"): "20261022T205721-edge-tuned-nosync-B-par",
        ("edge", "src"): "20261022T174101-edge-tuned-nosync-B-src",
        ("cloud", "seq"): "20261022T180405-cloud-tuned-nosync-B-seq",
        ("cloud", "par"): "20261022T182456-cloud-tuned-nosync-B-par",
        ("cloud", "src"): "20261022T184559-cloud-tuned-nosync-B-src",
    },
    "C": {  # push with EDC defaults (1000 ms state-machine wait, database sync on)
        "hybrid": "20261022T195601-hybrid-default-C-default",
        "edge": "20261022T200735-edge-default-C-default",
        "cloud": "20261022T201851-cloud-default-C-default",
    },
    "D": {  # enforcement
        ("hybrid", "enf"): "20261022T190900-hybrid-tuned-nosync-D-enf",
        ("edge", "enf"): "20261022T203726-edge-tuned-nosync-D-enf",
        ("cloud", "enf"): "20261022T204717-cloud-tuned-nosync-D-enf",
        ("hybrid", "linkcut"): "20261022T203027-hybrid-tuned-nosync-D-linkcut",
    },
}

_cache = {}


def load(run_dir):
    """summary.json of a run directory name."""
    if run_dir not in _cache:
        _cache[run_dir] = json.loads((RESULTS / run_dir / "summary.json").read_text())
    return _cache[run_dir]


def raw(run_dir, name):
    """Any JSON file of a run directory, e.g. raw(d, 'pull-pull-tc1.json')."""
    return json.loads((RESULTS / run_dir / name).read_text())


def boot_ci(values, stat=np.median, n=10000, level=0.95, seed=1):
    """Percentile bootstrap confidence interval of `stat` (Efron 1979); fixed seed for reproducibility."""
    v = np.asarray([x for x in values if x is not None], dtype=float)
    if len(v) == 0:
        return (np.nan, np.nan)
    rng = np.random.default_rng(seed)
    boots = stat(rng.choice(v, size=(n, len(v)), replace=True), axis=1)
    a = (1 - level) / 2
    return (float(np.quantile(boots, a)), float(np.quantile(boots, 1 - a)))


def mwu(a, b):
    """Two-sided Mann–Whitney U; returns (U, p)."""
    r = stats.mannwhitneyu(a, b, alternative="two-sided")
    return float(r.statistic), float(r.pvalue)


# Font scale: figures are drawn 6.1 in wide and shrink to the 15 cm text width,
# so 9 pt text rendered at about 7.5 pt against 12 pt body text. FS brings figure
# text to about 9.5-10 pt in the PDF (TAU writing tips: figure text should not be
# much smaller than the body text). Scripts with hand-placed text multiply by FS too.
FS = 1.25


def style():
    plt.rcParams.update({
        "font.size": 9 * FS, "axes.titlesize": 9 * FS, "axes.labelsize": 9 * FS, "legend.fontsize": 8 * FS,
        "xtick.labelsize": 8 * FS, "ytick.labelsize": 8 * FS, "axes.spines.top": False, "axes.spines.right": False,
        "figure.dpi": 150, "savefig.bbox": "tight", "pdf.fonttype": 42,
    })


WIDTH = 6.1   # inches, the TAU template's text width (about 15.5 cm)


def savefig(fig, name):
    """images/results/<name>.pdf for the thesis, analysis/out/png/<name>.png for review."""
    fig.savefig(FIG_DIR / f"{name}.pdf")
    fig.savefig(OUT / "png" / f"{name}.png", dpi=200)
    plt.close(fig)


def write_table(name, latex):
    """A LaTeX tabular (or table body) for \\input in the thesis."""
    (OUT / "tables" / f"{name}.tex").write_text(latex)


def write_numbers(name, obj):
    """Every number a chapter quotes, as JSON, so the text can be checked against it."""
    (OUT / f"{name}.json").write_text(json.dumps(obj, indent=2, default=float))


style()
