#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# render.sh — renders every .mmd here (and in split/) to out/<name>.svg,
# .pdf and .png (2x scale). A syntax error in a diagram fails the script.
#
#   bash diagrams/render.sh           the pull diagrams, into out/
#   bash diagrams/render.sh push      the push diagrams (build_push.py), into push/out/
#
# Needs the Mermaid CLI and Node.js 18 or newer. By default it runs
#   npx -y @mermaid-js/mermaid-cli
# Override with:
#   MMDC=<path to mmdc>                 an installed CLI
#   PUPPETEER_CONFIG=<json file>        puppeteer options, e.g. to use the
#                                       installed Chrome:
#     {"executablePath": "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
#      "args": ["--no-sandbox"], "headless": "shell"}
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail
cd "$(dirname "$0")/${1:-.}"

read -r -a MMDC <<< "${MMDC:-npx -y @mermaid-js/mermaid-cli}"
PP=()
[[ -n "${PUPPETEER_CONFIG:-}" ]] && PP=(-p "$PUPPETEER_CONFIG")

mkdir -p out out/split
for f in *.mmd split/*.mmd; do
  base="${f%.mmd}"
  echo "→ $f"
  "${MMDC[@]}" ${PP[@]+"${PP[@]}"} -q -i "$f" -o "out/$base.svg"
  "${MMDC[@]}" ${PP[@]+"${PP[@]}"} -q -i "$f" -o "out/$base.pdf"
  "${MMDC[@]}" ${PP[@]+"${PP[@]}"} -q -i "$f" -o "out/$base.png" -s 2
done
echo "Done: $(ls out/*.svg out/split/*.svg | wc -l | tr -d ' ') diagrams in $(pwd)/out"
