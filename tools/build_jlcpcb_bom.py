#!/usr/bin/env python3
"""Build JLCPCB/LCSC BOM review files from the KiCad schematic BOM export.

The KiCad export remains the source of truth for designators, values, and
assigned footprints. LCSC part numbers are resolved in priority order:
  1. Raw schematic LCSC column (set via KiCad symbol properties + sync script)
  2. bom/parts_db.csv keyed by (value, footprint)  ← preferred for new parts
  3. OVERRIDES dict below (deprecated — kept until schematic sync is complete)
  4. Empty string (unresolved)
"""

from __future__ import annotations

import argparse
import csv
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


RAW_BOM = Path("bom/smart_pouch_kicad_bom_raw.csv")
TECHNICAL_WORKBOOK = Path("bom/smart_pouch_technical_reference.xlsx")
JLC_CART_WORKBOOK = Path("bom/JLC_CART.xlsx")
DEFAULT_PARTS_DB = Path("bom/parts_db.csv")


@dataclass(frozen=True)
class Override:
    lcsc: str = ""
    manufacturer: str = ""
    mpn: str = ""
    footprint: str = ""
    note: str = ""
    manual: bool = False


# DEPRECATED: OVERRIDES is keyed by schematic ref-string (e.g. "C1,C4,C6").
# This breaks silently when refs are renumbered or parts are added.
# New part assignments belong in bom/parts_db.csv (value+footprint keyed).
# Kept as a fallback until schematic LCSC fields are fully populated.
# Do not add new entries here.
OVERRIDES: dict[str, Override] = {
    "C1,C4,C6,C8,C12-C15,C29-C33": Override(
        "C307331",
        note="100 nF 0402 X7R 50 V; chosen over 16 V parts for rail-margin safety.",
    ),
    "C2,C3,C5,C11,C24": Override("C52923", note="1 uF 0402 X5R 25 V."),
    "C7,C16,C18,C20-C23": Override("C15850", note="10 uF 0805 X5R 25 V."),
    "C16,C18": Override("C15850", note="10 uF 0805 X5R 25 V."),
    "C17,C19": Override("C52306", note="22 uF 1210 X5R 25 V."),
    "C25": Override(
        "C778333",
        note="RF antenna matching capacitor. Original schematic said 0.5uF, but this is the nRF52840 antenna match; using stocked 0.6pF 0402 C0G.",
    ),
    "C26": Override(
        "C3875120",
        note="RF antenna matching capacitor. Original schematic said 0.8uF, but this is the nRF52840 antenna match; using 0.8pF 0402 C0G.",
    ),
    "C27,C35": Override("C1547", note="12 pF 0402 C0G/NP0 50 V."),
    "D1,D6-D12": Override("C2843891", note="White 3030 LED; verify current/thermal target."),
    "D5": Override("C2827688", note="PRTR5V0U2X USB ESD."),
    "J1": Override(
        "C146125",
        footprint="easyeda2kicad:CONN-SMD_2P-P2.54_XH2.54-2AB",
        note="SMD 2-pin XH-style connector for +12 V siren/load output; intentionally different from battery PH connector.",
    ),
    "J2": Override(
        "C2681544",
        footprint="easyeda2kicad:CONN-SMD_2.54-3P-LT",
        note="SMD 3-pin 2.54 mm connector selected for the trimmer/control path.",
    ),
    "J3": Override("C266888", note="SIM card connector SMN-303."),
    "L2,L3": Override(
        "C2849472",
        footprint="easyeda2kicad:IND-SMD_L4.0-W4.0",
        note="10 uH shielded power inductor, 4x4 mm class.",
    ),
    "L4,L5": Override(
        "C92959",
        footprint="easyeda2kicad:IND-SMD_L4.0-W4.0_NRS4018T",
        note="2.2 uH shielded power inductor, 4x4 mm class.",
    ),
    "L6": Override(
        "C86065",
        footprint="easyeda2kicad:L0402-R-RD",
        note="4.7 nH RF matching inductor; schematic footprint should be 0402, not the 4x4 power inductor footprint.",
    ),
    "P1": Override("C456012", note="USB-C 6-pin receptacle."),
    "Q1,Q2,Q4": Override("C3018484", note="BSS84 P-channel MOSFET."),
    "Q3,Q5,Q6": Override("C8545", note="2N7002 N-channel MOSFET."),
    "R1": Override("C25792", note="47 kOhm 0402 1%."),
    "R2": Override("C22369540", note="150 kOhm 0402 1%."),
    "R3,R4,R20,R22": Override("C49330233", note="10 kOhm 0402 1%; min-1 alternative to Basic C25744."),
    "R5,R6,R28": Override(
        "C25104",
        footprint="Resistor_SMD:R_0402_1005Metric",
        note="330 Ohm 0402 1%; schematic footprint was blank.",
    ),
    "R7-R14": Override("C25169", note="4.7 Ohm 0402 5%; verify tolerance is acceptable."),
    "R15": Override("C25905", note="5.1 kOhm 0402 1%."),
    "R16,R17": Override("C100318", note="22 Ohm 0402 1%."),
    "R18,R23,R24": Override("C25076", note="100 Ohm 0402 1%."),
    "R19": Override("C159084", note="191 kOhm 0402 1%."),
    "R21": Override("C64043", note="240 kOhm 0402 1%."),
    "R25": Override("C144809", note="100 kOhm 0402 1%; min-1 alternative to Basic C25741."),
    "R26,R27": Override("C25900", note="4.7 kOhm 0402 1%."),
    "RV1": Override(
        "C719176",
        footprint="easyeda2kicad:RES-ADJ-SMD_3P-L3.0-W3.8-P1.75-BR",
        note="10 kOhm SMD trimmer selected; schematic/spec did not define a previous resistance value.",
    ),
    "SW1": Override(
        "C139797",
        footprint="easyeda2kicad:KEY-SMD_4P-L4.2-W3.2-P2.20-LS4.6",
        note="SMD tactile switch imported with easyeda2kicad.",
    ),
    "TH1": Override("C77131", note="10 kOhm 0402 NTC thermistor."),
    "U1": Override("C190794", note="nRF52840-QIAA-R."),
    "U2": Override("C22397843", note="nRF9151-LACA-R7 selected."),
    "U9": Override(
        "C160404",
        footprint="easyeda2kicad:CONN-SMD_4P-P1.00_SM04B-SRSS-TB-LF-SN",
        note="SMD JST-SH 1.0 mm 4-pin UART connector.",
    ),
    "U11,U14": Override(
        "C41376037",
        footprint="easyeda2kicad:HDR-SMD_10P-P1.27-V-M-R2-C5-LS5.5_1",
        note="SMD 2x5 1.27 mm SWD header replacing through-hole header.",
    ),
    "CN1": Override(
        "C160352",
        footprint="easyeda2kicad:CONN-SMD_B2B-PH-SM4-TB-LF-SN",
        note="SMD JST PH 2-pin battery connector replacing through-hole B2B-PH-K-S.",
    ),
    "Y1": Override("C187794", note="32 MHz 2016 crystal, 8 pF load; verify against final nRF52840 load-cap calculation."),
    "D3": Override("C151304", note="SP3012-04UTG SIM ESD protection array."),
    "D13-D15": Override("C8678", note="SS34 40V 3A Schottky diode SMA."),
    "LED1,LED2": Override("C60105", note="19-237/R6GHBHC-A01/2T bicolor red/green status LED."),
    "U3": Override("C25346894", note="nPM1300-CAAA-R7 PMIC."),
    "U4": Override("C437655", note="BMA400 accelerometer LGA-12."),
    "U6,U10": Override("C5137195", note="u.FL / IPEX1 SMD RF connector."),
    "U7": Override("C239238", note="AN6520-245 2.4/5 GHz antenna."),
    "U8": Override("C160405", note="SM06B-SRSS-TB JST SH 1.0 mm 6-pin biometric connector."),
    "U12,U13": Override("C84817", note="MT3608 boost converter SOT-23-6."),
}


PART_WARNINGS: dict[str, str] = {}


def load_parts_db(path: Path) -> dict[tuple[str, str], dict[str, str]]:
    """Load parts_db.csv keyed by (value.lower(), footprint). Returns {} if missing."""
    if not path.exists():
        return {}
    db: dict[tuple[str, str], dict[str, str]] = {}
    with path.open(newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            key = (row["value"].lower().strip(), row["footprint"].strip())
            db[key] = row
    return db


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw", type=Path, default=RAW_BOM)
    parser.add_argument("--parts-db", type=Path, default=DEFAULT_PARTS_DB,
                        help="Path to parts_db.csv (default: bom/parts_db.csv)")
    parser.add_argument("--board-qty", type=int, default=2, help="Number of boards for cart/order quantities.")
    parser.add_argument("--no-network", action="store_true", help="Do not refresh JLCPCB data.")
    return parser.parse_args()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def split_ref_token(token: str) -> tuple[str, int] | None:
    match = re.fullmatch(r"([A-Za-z]+)(\d+)", token.strip())
    if not match:
        return None
    return match.group(1), int(match.group(2))


def expand_refs(refs: str) -> list[str]:
    expanded: list[str] = []
    for item in refs.split(","):
        item = item.strip()
        if "-" not in item:
            expanded.append(item)
            continue
        start, end = item.split("-", 1)
        start_ref = split_ref_token(start)
        end_ref = split_ref_token(end)
        if not start_ref or not end_ref or start_ref[0] != end_ref[0]:
            expanded.append(item)
            continue
        prefix = start_ref[0]
        expanded.extend(f"{prefix}{number}" for number in range(start_ref[1], end_ref[1] + 1))
    return expanded


def dec(value: Any) -> Decimal | None:
    try:
        if value in (None, ""):
            return None
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def get_attr(obj: Any, name: str, default: Any = "") -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def normalize_search_results(results: Any) -> list[Any]:
    if isinstance(results, dict):
        inner = results.get("results", [])
        return inner if isinstance(inner, list) else []
    if isinstance(results, list):
        return results
    return list(results) if results else []


def fetch_live_parts(lcsc_ids: set[str], no_network: bool) -> dict[str, dict[str, Any]]:
    if no_network or not lcsc_ids:
        return {}
    try:
        from easyeda2kicad.easyeda.easyeda_api import EasyedaApi
    except Exception as exc:  # pragma: no cover - depends on local install
        print(f"Warning: easyeda2kicad API unavailable: {exc}")
        return {}

    api = EasyedaApi()
    live: dict[str, dict[str, Any]] = {}
    for lcsc_id in sorted(lcsc_ids):
        try:
            results = normalize_search_results(api.search_jlcpcb_components(lcsc_id, page_size=10))
        except Exception as exc:  # pragma: no cover - network dependent
            print(f"Warning: JLCPCB lookup failed for {lcsc_id}: {exc}")
            continue
        exact = None
        for result in results:
            if get_attr(result, "lcsc") == lcsc_id:
                exact = result
                break
        if exact is None and results:
            exact = results[0]
        if exact is None:
            continue
        live[lcsc_id] = {
            "lcsc": get_attr(exact, "lcsc"),
            "manufacturer": get_attr(exact, "brand"),
            "mpn": get_attr(exact, "model"),
            "package": get_attr(exact, "package"),
            "description": get_attr(exact, "description"),
            "library_type": get_attr(exact, "type"),
            "stock": get_attr(exact, "stock"),
            "min_qty": get_attr(exact, "min_qty"),
            "reel_qty": get_attr(exact, "reel_qty"),
            "price": get_attr(exact, "price"),
        }
    return live


def build_rows(raw_rows: list[dict[str, str]], live: dict[str, dict[str, Any]], board_qty: int, parts_db: dict[tuple[str, str], dict[str, str]] | None = None) -> list[dict[str, Any]]:
    if parts_db is None:
        parts_db = {}
    rows: list[dict[str, Any]] = []
    for raw in raw_rows:
        refs = raw.get("Refs") or raw.get("Reference", "")
        raw_value = raw.get("Value", "").strip()
        raw_footprint = raw.get("Footprint", "").strip()

        # Priority 1: LCSC from schematic (populated by sync_lcsc_to_sch.py)
        lcsc = raw.get("LCSC Part", raw.get("LCSC", "")).strip()

        # Priority 2: parts_db lookup by (value, footprint)
        db_entry: dict[str, str] = {}
        if not lcsc:
            db_entry = parts_db.get((raw_value.lower(), raw_footprint), {})
            lcsc = db_entry.get("lcsc", "").strip()

        # Priority 3: OVERRIDES (deprecated fallback)
        override = OVERRIDES.get(refs, Override())
        if not lcsc:
            lcsc = override.lcsc

        live_part = live.get(lcsc, {})

        # Footprint: parts_db > OVERRIDES > raw schematic
        effective_footprint = db_entry.get("footprint", "").strip() or override.footprint or raw_footprint
        qty_per_board = len(expand_refs(refs))
        order_qty = qty_per_board * board_qty
        min_qty = int(live_part.get("min_qty") or 0)
        suggested_cart_qty = max(order_qty, min_qty or order_qty)
        unit_price = dec(live_part.get("price"))
        order_total = unit_price * Decimal(order_qty) if unit_price is not None else None
        suggested_total = unit_price * Decimal(suggested_cart_qty) if unit_price is not None else None
        note_parts = []
        if db_entry.get("note"):
            note_parts.append(db_entry["note"])
        elif override.note:
            note_parts.append(override.note)
        if lcsc in PART_WARNINGS:
            note_parts.append(PART_WARNINGS[lcsc])
        if not lcsc:
            note_parts.append("No LCSC/JLCPCB part selected yet.")
        if override.manual:
            note_parts.append("Manual review required.")
        rows.append(
            {
                "Designators": ",".join(expand_refs(refs)),
                "Value": raw_value,
                "KiCad Footprint": effective_footprint,
                "LCSC Part #": lcsc,
                "Manufacturer": live_part.get("manufacturer") or db_entry.get("manufacturer") or override.manufacturer or raw.get("Manufacturer", ""),
                "MFR Part #": live_part.get("mpn") or db_entry.get("mpn") or override.mpn or raw.get("MPN", ""),
                "Description": live_part.get("description", ""),
                "Package": live_part.get("package", ""),
                "Library Type": live_part.get("library_type", ""),
                "Stock": live_part.get("stock", ""),
                "Min Qty": min_qty or "",
                "Reel Qty": live_part.get("reel_qty", ""),
                "Board Qty": board_qty,
                "Qty Per Board": qty_per_board,
                "Order Qty": order_qty,
                "Suggested Cart Qty": suggested_cart_qty if lcsc else "",
                "Unit Price": str(unit_price) if unit_price is not None else "",
                "Order Total": str(order_total) if order_total is not None else "",
                "Suggested Cart Total": str(suggested_total) if suggested_total is not None else "",
                "Notes": " ".join(note_parts),
            }
        )
    return rows



def _style_sheet(ws: Any, sheet_name: str) -> None:
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.table import Table, TableStyleInfo

    header_fill = PatternFill("solid", fgColor="1F4E78")
    header_font = Font(color="FFFFFF", bold=True)
    thin = Side(style="thin", color="D9E2F3")
    border = Border(bottom=thin)

    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    for cell in ws[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = border
    for data_row in ws.iter_rows(min_row=2):
        for cell in data_row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)
    for col_idx in range(1, ws.max_column + 1):
        letter = get_column_letter(col_idx)
        max_len = max(
            (min(len("" if cell.value is None else str(cell.value)), 70) for cell in ws[letter]),
            default=0,
        )
        ws.column_dimensions[letter].width = max(10, min(max_len + 2, 55))

    if ws.max_row >= 2 and ws.max_column >= 2:
        table_ref = f"A1:{get_column_letter(ws.max_column)}{ws.max_row}"
        table = Table(displayName=f"{sheet_name.replace(' ', '')}Table", ref=table_ref)
        table.tableStyleInfo = TableStyleInfo(
            name="TableStyleMedium2",
            showFirstColumn=False,
            showLastColumn=False,
            showRowStripes=True,
            showColumnStripes=False,
        )
        ws.add_table(table)


def write_single_sheet_xlsx(path: Path, sheet_name: str, rows: list[dict[str, Any]], headers: list[str]) -> None:
    try:
        from openpyxl import Workbook
    except Exception as exc:  # pragma: no cover - depends on local install
        print(f"Warning: could not write {path}: openpyxl unavailable: {exc}")
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = sheet_name[:31]
    ws.append(headers)
    for row in rows:
        ws.append([row.get(header, "") for header in headers])
    _style_sheet(ws, sheet_name)
    wb.save(path)


def main() -> None:
    args = parse_args()
    raw_rows = read_csv(args.raw)
    parts_db = load_parts_db(args.parts_db)

    # Collect LCSC IDs from all three priority sources for the live lookup.
    lcsc_ids: set[str] = set()
    for row in raw_rows:
        lcsc = row.get("LCSC Part", row.get("LCSC", "")).strip()
        if not lcsc:
            db_entry = parts_db.get((row.get("Value", "").lower().strip(), row.get("Footprint", "").strip()), {})
            lcsc = db_entry.get("lcsc", "").strip()
        if not lcsc:
            refs = row.get("Refs") or row.get("Reference", "")
            lcsc = OVERRIDES.get(refs, Override()).lcsc
        if lcsc:
            lcsc_ids.add(lcsc)

    live = fetch_live_parts(lcsc_ids, args.no_network)
    rows = build_rows(raw_rows, live, args.board_qty, parts_db)

    review_headers = [
        "Designators",
        "Value",
        "KiCad Footprint",
        "LCSC Part #",
        "Manufacturer",
        "MFR Part #",
        "Description",
        "Package",
        "Library Type",
        "Stock",
        "Min Qty",
        "Reel Qty",
        "Board Qty",
        "Qty Per Board",
        "Order Qty",
        "Suggested Cart Qty",
        "Unit Price",
        "Order Total",
        "Suggested Cart Total",
        "Notes",
    ]

    cart_headers = [
        "Parts Type", "JLCPCB Part #", "MFR Part #", "Description",
        "Unit Price", "Qty", "Total Price",
    ]
    cart_rows = [
        {
            "Parts Type": row["Library Type"],
            "JLCPCB Part #": row["LCSC Part #"],
            "MFR Part #": row["MFR Part #"],
            "Description": row["Description"],
            "Unit Price": row["Unit Price"],
            "Qty": row["Order Qty"],
            "Total Price": row["Order Total"],
        }
        for row in rows
        if row["LCSC Part #"]
    ]

    write_single_sheet_xlsx(JLC_CART_WORKBOOK, "Cart", cart_rows, cart_headers)
    write_single_sheet_xlsx(TECHNICAL_WORKBOOK, "Reference", rows, review_headers)

    print(f"Wrote {JLC_CART_WORKBOOK} ({len(cart_rows)} parts)")
    print(f"Wrote {TECHNICAL_WORKBOOK} ({len(rows)} parts)")


if __name__ == "__main__":
    main()
