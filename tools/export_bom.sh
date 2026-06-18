#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
flatpak run --command=kicad-cli org.kicad.KiCad sch export bom \
  --output bom/smart_pouch_kicad_bom_raw.csv \
  --fields "Reference,Value,Footprint,Datasheet,LCSC Part,Manufacturer,MPN,Description" \
  --labels "Reference,Value,Footprint,Datasheet,LCSC,Manufacturer,MPN,Description" \
  --group-by "Value,Footprint,LCSC Part,Manufacturer,MPN" \
  --sort-field Reference \
  --exclude-dnp \
  smart_pouch.kicad_sch
echo "Exported bom/smart_pouch_kicad_bom_raw.csv"
