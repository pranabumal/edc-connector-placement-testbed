#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# render_thesis_figures.sh — turns thesis/F4_*.svg (written by
# build_thesis_figures.py) into the PDFs the thesis includes
# (<thesis>/images/testbed/) and PNG previews (thesis/png/).
# Uses headless Google Chrome; override the path with CHROME=<binary>.
# The PDF page has exactly the size of the figure and the text stays vector.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail
cd "$(dirname "$0")"
CHROME="${CHROME:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"
# Into the thesis sources when they sit next to this repository (or THESIS_DIR
# names them); otherwise into figures/ of this repository.
THESIS="${THESIS_DIR:-../../Thesis Writing TAU}"
[[ -d "$THESIS" ]] || THESIS="../figures"
DEST="$THESIS/images/testbed"
mkdir -p thesis/png "$DEST"

for f in thesis/F4_[1-6]_*.svg; do
  name="$(basename "$f" .svg)"
  w="$(grep -o ' width="[0-9]*"' "$f" | head -1 | tr -dc 0-9)"
  h="$(grep -o ' height="[0-9]*"' "$f" | head -1 | tr -dc 0-9)"
  echo "→ $f (${w}x${h})"
  "$CHROME" --headless=new --hide-scrollbars --force-device-scale-factor=2 --window-size="$w,$h" \
    --screenshot="$PWD/thesis/png/$name.png" "file://$PWD/$f" > /dev/null 2>&1
  { echo "<!doctype html><html><head><meta charset=\"utf-8\"><style>@page{size:${w}px ${h}px;margin:0}html,body{margin:0}svg{display:block}</style></head><body>"
    cat "$f"; echo "</body></html>"; } > "thesis/.$name.html"
  "$CHROME" --headless=new --no-pdf-header-footer --print-to-pdf="$PWD/$DEST/$name.pdf" \
    "file://$PWD/thesis/.$name.html" > /dev/null 2>&1
  rm -f "thesis/.$name.html"
done
echo "Done: PDFs in $DEST, previews in thesis/png"
