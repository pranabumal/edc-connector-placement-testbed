#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# render_architecture.sh — turns architecture/*.svg (written by
# build_architecture.py) into out/architecture/<name>.svg, .pdf and .png (2x).
# Uses headless Google Chrome; override the path with CHROME=<binary>.
# With the argument "push" it works in push/ instead (build_push.py).
# The PDF page has exactly the size of the figure and the text stays vector.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail
cd "$(dirname "$0")/${1:-.}"
CHROME="${CHROME:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"
mkdir -p out/architecture

for f in architecture/*.svg; do
  name="$(basename "$f" .svg)"
  w="$(grep -o ' width="[0-9]*"' "$f" | head -1 | tr -dc 0-9)"
  h="$(grep -o ' height="[0-9]*"' "$f" | head -1 | tr -dc 0-9)"
  echo "→ $f (${w}x${h})"
  cp "$f" "out/architecture/$name.svg"
  "$CHROME" --headless=new --hide-scrollbars --force-device-scale-factor=2 --window-size="$w,$h" \
    --screenshot="$PWD/out/architecture/$name.png" "file://$PWD/$f" > /dev/null 2>&1
  { echo "<!doctype html><html><head><meta charset=\"utf-8\"><style>@page{size:${w}px ${h}px;margin:0}html,body{margin:0}svg{display:block}</style></head><body>"
    cat "$f"; echo "</body></html>"; } > "out/architecture/.$name.html"
  "$CHROME" --headless=new --no-pdf-header-footer --print-to-pdf="$PWD/out/architecture/$name.pdf" \
    "file://$PWD/out/architecture/.$name.html" > /dev/null 2>&1
  rm -f "out/architecture/.$name.html"
done
echo "Done: $(ls out/architecture/*.pdf | wc -l | tr -d ' ') architecture diagrams in $PWD/out/architecture"
