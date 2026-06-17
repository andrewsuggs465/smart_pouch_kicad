# Smart Pouch Hardware Review Handoff

This repository contains the KiCad design, current JLCPCB BOM outputs, project
specification, and component datasheets for the Smart Pouch PCB.

## Current Design Files

- `smart_pouch.kicad_sch` - current schematic
- `smart_pouch.kicad_pcb` - current PCB file
- `smart_pouch.kicad_pro` - KiCad project
- `sym-lib-table` - project symbol library table

## BOM and Ordering Files

Final BOM files are in `bom/`.

- `bom/smart_pouch_jlcpcb_upload_bom.csv` - clean JLCPCB PCBA upload BOM
- `bom/smart_pouch_jlcpcb_cart_sheet.xlsx` - workbook for JLCPCB cart/order review
- `bom/smart_pouch_technical_reference.xlsx` - technical reference workbook
- `bom/smart_pouch_jlcpcb_bom_review.csv` - stock/MOQ/library review
- `bom/smart_pouch_jlcpcb_cart.csv` - cart-style CSV

For JLCPCB upload, start with `bom/smart_pouch_jlcpcb_upload_bom.csv`.
Map `JLCPCB Part #` as the LCSC/JLC part-number column.

## Documentation

- `docs/spec/securepouch_spec.pdf` - project specification PDF
- `docs/spec/securepouch_spec.tex` - source for the specification
- `docs/datasheets/` - component datasheets used during review

## Reports

- `reports/ERC_codex_after_bom_moq.rpt` - latest ERC report, 0 violations

## Scripts

- `tools/build_jlcpcb_bom.py` - regenerates the JLCPCB BOM outputs from the KiCad BOM export

Typical refresh flow:

```bash
flatpak run --command=kicad-cli org.kicad.KiCad sch export bom \
  --output bom/smart_pouch_kicad_bom_raw.csv \
  --fields 'Reference,Value,Footprint,QUANTITY,Manufacturer,MPN,LCSC Part,Datasheet,DNP' \
  --labels 'Refs,Value,Footprint,Qty,Manufacturer,MPN,LCSC Part,Datasheet,DNP' \
  --group-by 'Value,Footprint,Manufacturer,MPN,LCSC Part,DNP' \
  --sort-field Reference \
  --exclude-dnp smart_pouch.kicad_sch

python3 tools/build_jlcpcb_bom.py
```

## Archive

Old ERC reports, temporary netlists, KiCad backups, LaTeX build artifacts, and
legacy spreadsheets are stored under `archive/` so they are available if needed
without cluttering the review path.
