#!/bin/bash
# Baseline screenshot script for Step 4
# Usage: ./tools/baseline_screenshots.sh <SAMOVAR_IP>
# Example: ./tools/baseline_screenshots.sh 192.168.1.100

set -e

IP="${1:?Usage: $0 <SAMOVAR_IP>}"
BASE_URL="http://${IP}"
OUT_DIR="docs/result/delivery/baseline_screenshots"

echo "Taking baseline screenshots from ${BASE_URL}..."

PAGES=(
  "index.htm:mode_rect"
  "beer.htm:mode_beer"
  "distiller.htm:mode_dist"
  "nbk.htm:mode_nbk"
  "bk.htm:mode_bk"
  "setup.htm:setup"
  "program.htm:program"
  "chart.htm:chart"
  "calibrate.htm:calibrate"
)

playwright-cli open "${BASE_URL}/index.htm"
sleep 3

for entry in "${PAGES[@]}"; do
  page="${entry%%:*}"
  name="${entry##*:}"
  echo "  → ${page} (${name})"
  playwright-cli goto "${BASE_URL}/${page}"
  sleep 2
  playwright-cli screenshot --filename="${OUT_DIR}/${name}.png"
done

playwright-cli close
echo "Done. Screenshots saved to ${OUT_DIR}/"
