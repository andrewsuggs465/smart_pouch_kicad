#!/usr/bin/env bash
# Usage: bash tools/make_bom.sh [--no-network] [--board-qty N]
set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> Exporting raw BOM from schematic..."
flatpak run --command=kicad-cli org.kicad.KiCad sch export bom \
  --output bom/smart_pouch_kicad_bom_raw.csv \
  --fields "Reference,Value,Footprint,Datasheet,LCSC Part,Manufacturer,MPN,Description" \
  --labels "Reference,Value,Footprint,Datasheet,LCSC,Manufacturer,MPN,Description" \
  --group-by "Value,Footprint,LCSC Part,Manufacturer,MPN" \
  --sort-field Reference \
  --exclude-dnp \
  smart_pouch.kicad_sch

echo "==> Building JLCPCB BOM..."
python3 tools/build_jlcpcb_bom.py "$@"
