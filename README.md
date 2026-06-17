# Smart Pouch

KiCad schematic and PCB for the Smart Pouch hardware.

## Design files

- `smart_pouch.kicad_sch` — schematic
- `smart_pouch.kicad_pcb` — PCB layout
- `docs/spec/securepouch_spec.tex` — product specification

## BOM workflow

Part assignments live in two places:
- **Schematic** — each symbol has an `LCSC Part` property
- **`bom/parts_db.csv`** — keyed by `value + footprint`; add new part types here

Regenerate after schematic changes:
```bash
bash tools/make_bom.sh                 # live JLCPCB pricing/stock
bash tools/make_bom.sh --no-network    # offline
bash tools/make_bom.sh --board-qty 5  # change order quantity (default 2)
```

Outputs written to `bom/`:
- `JLC_CART.xlsx` — upload this to the JLCPCB BOM tool to order parts
- `smart_pouch_technical_reference.xlsx` — internal reference with stock and pricing

## Adding a new part

Set the `LCSC Part` property on the symbol in KiCad, **or** add a row to `bom/parts_db.csv`:
```
value,footprint,lcsc,manufacturer,mpn,note
100nF,Capacitor_SMD:C_0402_1005Metric,C307331,,,
```

To find the right LCSC number, run the part selector — it queries JLCPCB and ranks candidates:
```bash
python3 tools/select_parts.py --dry-run       # preview proposals
python3 tools/select_parts.py --interactive   # approve each one interactively
```

## Other tools

```bash
# Sync LCSC numbers from parts_db back into schematic symbol properties
python3 tools/sync_lcsc_to_sch.py

# Import a new symbol/footprint from LCSC into the easyeda2kicad library
easyeda2kicad --lcsc C<number> --output ~/Documents/Kicad/easyeda2kicad/
```
