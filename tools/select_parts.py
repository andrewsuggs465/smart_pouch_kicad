#!/usr/bin/env python3
"""AI-assisted part selector for the JLCPCB BOM pipeline.

Finds components with no LCSC assignment in the KiCad raw BOM export,
queries the JLCPCB API via easyeda2kicad for candidate parts, ranks
them, and proposes additions to bom/parts_db.csv for human review.

Usage:
    python3 tools/select_parts.py [OPTIONS]

Options:
    --raw PATH          Raw BOM CSV (default: bom/smart_pouch_kicad_bom_raw.csv)
    --parts-db PATH     Parts DB to update (default: bom/parts_db.csv)
    --dry-run           Print proposals without writing to parts_db.csv
    --top N             Show top N candidates per part (default: 3)
    --interactive       Prompt user to confirm each assignment (y/n/s to skip)
    --force             Re-evaluate parts that already have an LCSC assignment
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import sys
import tempfile
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

RAW_BOM = Path("bom/smart_pouch_kicad_bom_raw.csv")
PARTS_DB = Path("bom/parts_db.csv")

PARTS_DB_HEADERS = ["value", "footprint", "lcsc", "manufacturer", "mpn", "note"]


# ---------------------------------------------------------------------------
# Helpers (mirrored from build_jlcpcb_bom.py to avoid import coupling)
# ---------------------------------------------------------------------------

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


def dec(value: Any) -> Decimal | None:
    try:
        if value in (None, ""):
            return None
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


# ---------------------------------------------------------------------------
# Package extraction from KiCad footprint string
# ---------------------------------------------------------------------------

# Regexes ordered from most-specific to least-specific.
_PACKAGE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Standard passives: C_0402_…, R_0402_…, L_0402_…
    (re.compile(r"[CRLFD]_(\d{4})_\d+Metric", re.IGNORECASE), r"\1"),
    # Capacitor/Resistor with exact size label
    (re.compile(r"(?:Capacitor|Resistor|Inductor)_SMD:[CRLD]_(\d{4})"), r"\1"),
    # SOT-xx, SOD-xx, SOT-xxx-x
    (re.compile(r"(SOT-\d+(?:[A-Z]|-\d+[A-Z]?)?)", re.IGNORECASE), r"\1"),
    (re.compile(r"(SOD-\d+[A-Z]*)", re.IGNORECASE), r"\1"),
    # QFN/DFN/UDFN
    (re.compile(r"((?:Q|D|UDF)FN-\d+[^\s,]*)", re.IGNORECASE), r"\1"),
    # BGA
    (re.compile(r"(BGA-\d+[^\s,]*)", re.IGNORECASE), r"\1"),
    # LGA
    (re.compile(r"(LGA-\d+[^\s,]*)", re.IGNORECASE), r"\1"),
    # SMA/SMB/SMC diode packages
    (re.compile(r"(SM[ABC])[_\-]", re.IGNORECASE), r"\1"),
    # 0805, 1206, 1210, 2016, etc. bare size codes in the footprint name
    (re.compile(r"[^a-zA-Z](\d{4})[^a-zA-Z\d]"), r"\1"),
    # Last resort: grab trailing size-like token after last underscore
    (re.compile(r"_([A-Z0-9]{4,})$", re.IGNORECASE), r"\1"),
]


def extract_package(footprint: str) -> str:
    """Return the implied package from a KiCad footprint string."""
    # Strip library prefix (everything before and including the colon)
    fp = footprint.split(":")[-1] if ":" in footprint else footprint
    for pattern, repl in _PACKAGE_PATTERNS:
        m = pattern.search(fp)
        if m:
            result = pattern.sub(repl, m.group(0)).strip("-_")
            # Normalise bare 4-digit size codes: 0402, 0805, etc.
            if re.fullmatch(r"\d{4}", result):
                return result
            return result
    return ""


# ---------------------------------------------------------------------------
# Query-building
# ---------------------------------------------------------------------------

_PASSIVE_FOOTPRINT_RE = re.compile(
    r"(?:Capacitor|Resistor|Inductor|Ferrite|Thermistor)_SMD", re.IGNORECASE
)

_EASYEDA_PASSIVE_RE = re.compile(
    r"easyeda2kicad:(?:C|R|L|IND|RES|CAP)_", re.IGNORECASE
)


def build_query(value: str, footprint: str) -> str:
    """Build a JLCPCB search query from value + footprint."""
    package = extract_package(footprint)
    is_passive = bool(
        _PASSIVE_FOOTPRINT_RE.search(footprint) or _EASYEDA_PASSIVE_RE.search(footprint)
    )
    if is_passive and package:
        return f"{value} {package}"
    if package:
        return f"{value} {package}"
    # For complex ICs/connectors just use the value
    return value


# ---------------------------------------------------------------------------
# Ranking
# ---------------------------------------------------------------------------

def _price_key(candidate: Any) -> Decimal:
    p = dec(get_attr(candidate, "price"))
    return p if p is not None else Decimal("9999")


def rank_candidates(candidates: list[Any], package: str) -> list[Any]:
    """Sort candidates: Basic first, then in-stock, then package-match, then price."""
    def sort_key(c: Any) -> tuple[int, int, int, Decimal]:
        is_basic = 0 if str(get_attr(c, "type", "")).lower() == "basic" else 1
        stock = get_attr(c, "stock", 0)
        in_stock = 0 if (isinstance(stock, int) and stock > 0) or (isinstance(stock, str) and stock.isdigit() and int(stock) > 0) else 1
        # Package match: lower is better (0 = exact, 1 = no match)
        cand_pkg = str(get_attr(c, "package", "")).upper()
        pkg_match = 0 if (package and package.upper() in cand_pkg) else 1
        price = _price_key(c)
        return (is_basic, in_stock, pkg_match, price)

    return sorted(candidates, key=sort_key)


# ---------------------------------------------------------------------------
# Parts DB I/O
# ---------------------------------------------------------------------------

def load_parts_db(path: Path) -> dict[tuple[str, str], dict[str, str]]:
    """Return {(value, footprint): row} from parts_db.csv."""
    if not path.exists():
        return {}
    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        rows: dict[tuple[str, str], dict[str, str]] = {}
        for row in reader:
            key = (row.get("value", "").strip(), row.get("footprint", "").strip())
            rows[key] = row
        return rows


def write_parts_db(path: Path, rows: list[dict[str, str]]) -> None:
    """Atomically write parts_db.csv."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=PARTS_DB_HEADERS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Stock formatting
# ---------------------------------------------------------------------------

def fmt_stock(stock: Any) -> str:
    try:
        n = int(stock)
        if n >= 1_000_000:
            return f"{n // 1_000_000}M"
        if n >= 1_000:
            return f"{n // 1_000}k"
        return str(n)
    except (TypeError, ValueError):
        return str(stock) if stock else "?"


# ---------------------------------------------------------------------------
# Main logic
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="AI-assisted JLCPCB part selector.")
    p.add_argument("--raw", type=Path, default=RAW_BOM,
                   help="Raw KiCad BOM CSV (default: bom/smart_pouch_kicad_bom_raw.csv)")
    p.add_argument("--parts-db", type=Path, default=PARTS_DB,
                   help="Parts DB CSV to read/update (default: bom/parts_db.csv)")
    p.add_argument("--dry-run", action="store_true",
                   help="Print proposals without writing to parts_db.csv")
    p.add_argument("--top", type=int, default=3,
                   help="Show top N candidates per part (default: 3)")
    p.add_argument("--interactive", action="store_true",
                   help="Prompt user to confirm each assignment")
    p.add_argument("--force", action="store_true",
                   help="Re-evaluate parts that already have an LCSC assignment")
    return p.parse_args()


def load_api() -> Any:
    try:
        from easyeda2kicad.easyeda.easyeda_api import EasyedaApi  # type: ignore
        return EasyedaApi()
    except ImportError as exc:
        print(f"Error: easyeda2kicad is not installed: {exc}", file=sys.stderr)
        sys.exit(1)


def search_candidates(api: Any, query: str, page_size: int = 20) -> list[Any]:
    try:
        results = api.search_jlcpcb_components(query, page_size=page_size)
        return normalize_search_results(results)
    except Exception as exc:
        raise RuntimeError(f"API call failed: {exc}") from exc


def process_part(
    api: Any,
    raw_row: dict[str, str],
    top_n: int,
    interactive: bool,
    dry_run: bool,
    parts_db_rows: list[dict[str, str]],
    db_keys: set[tuple[str, str]],
) -> dict[str, str] | None:
    """Process one raw BOM row. Returns a new parts_db row or None."""
    value = raw_row.get("Value", "").strip()
    footprint = raw_row.get("Footprint", "").strip()
    refs = raw_row.get("Refs", "").strip()

    package = extract_package(footprint)
    query = build_query(value, footprint)

    print(f"\n  Searching: '{query}'")

    try:
        candidates = search_candidates(api, query, page_size=max(top_n * 3, 20))
    except RuntimeError as exc:
        print(f"  Warning: {exc} — skipping.")
        return None

    if not candidates:
        print(f"  No candidates found for {value!r} {footprint!r}")
        return None

    ranked = rank_candidates(candidates, package)
    top = ranked[:top_n]

    # Display candidates
    print(f"  Candidates:")
    for i, cand in enumerate(top, 1):
        lcsc_id = get_attr(cand, "lcsc")
        lib_type = get_attr(cand, "type", "")
        stock = fmt_stock(get_attr(cand, "stock", 0))
        price = dec(get_attr(cand, "price"))
        price_str = f"${price}" if price is not None else "N/A"
        desc = get_attr(cand, "description", "")
        marker = " ← SELECTED" if i == 1 else ""
        print(f"    {i}. {lcsc_id:<10} {lib_type:<8} Stock:{stock:<8} {price_str:<8} {desc}{marker}")

    selected_idx = 0  # default: pick top-ranked

    if interactive:
        while True:
            try:
                choice = input(f"  Select [1-{len(top)}/s(skip)/q(quit)]: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print("\nAborted.")
                sys.exit(0)
            if choice == "q":
                print("Quit.")
                sys.exit(0)
            if choice in ("s", ""):
                print("  Skipped.")
                return None
            try:
                idx = int(choice) - 1
                if 0 <= idx < len(top):
                    selected_idx = idx
                    break
                else:
                    print(f"  Please enter a number between 1 and {len(top)}.")
            except ValueError:
                print("  Invalid input. Enter a number, 's' to skip, or 'q' to quit.")

    chosen = top[selected_idx]
    lcsc_id = str(get_attr(chosen, "lcsc"))
    manufacturer = str(get_attr(chosen, "brand", ""))
    mpn = str(get_attr(chosen, "model", ""))
    lib_type = str(get_attr(chosen, "type", ""))
    desc = str(get_attr(chosen, "description", ""))
    note = f"Auto-selected: {lib_type} {desc}".strip()

    row = {
        "value": value,
        "footprint": footprint,
        "lcsc": lcsc_id,
        "manufacturer": manufacturer,
        "mpn": mpn,
        "note": note,
    }

    if dry_run:
        print(f"  → Would write {lcsc_id} to parts_db.csv (dry-run)")
    else:
        print(f"  → Writing {lcsc_id} to parts_db.csv")

    return row


def main() -> None:
    args = parse_args()

    # Load raw BOM
    if not args.raw.exists():
        print(f"Error: raw BOM not found at {args.raw}", file=sys.stderr)
        sys.exit(1)

    with args.raw.open(newline="", encoding="utf-8-sig") as fh:
        raw_rows = list(csv.DictReader(fh))

    # Normalise column name: KiCad may export as "LCSC Part" or "LCSC"
    def get_lcsc(row: dict[str, str]) -> str:
        return (row.get("LCSC Part") or row.get("LCSC") or "").strip()

    # Load parts_db
    parts_db = load_parts_db(args.parts_db)
    db_keys: set[tuple[str, str]] = set(parts_db.keys())

    # Identify unresolved parts
    unresolved: list[dict[str, str]] = []
    for row in raw_rows:
        value = row.get("Value", "").strip()
        footprint = row.get("Footprint", "").strip()
        key = (value, footprint)

        # Skip if raw CSV already has an LCSC assignment (unless --force)
        if get_lcsc(row) and not args.force:
            continue

        # Skip if parts_db already has an entry for this (value, footprint) pair
        if key in db_keys and not args.force:
            continue

        unresolved.append(row)

    if not unresolved:
        print("All parts already have LCSC assignments. Use --force to re-evaluate.")
        return

    print(f"Unresolved parts: {len(unresolved)}")

    api = load_api()

    # Work through unresolved parts
    new_rows: list[dict[str, str]] = []
    for i, raw_row in enumerate(unresolved, 1):
        value = raw_row.get("Value", "").strip()
        footprint = raw_row.get("Footprint", "").strip()
        refs = raw_row.get("Refs", "").strip()
        print(f"\n[{i}/{len(unresolved)}] Value={value}  Footprint={footprint}  Refs={refs}")

        result = process_part(
            api=api,
            raw_row=raw_row,
            top_n=args.top,
            interactive=args.interactive,
            dry_run=args.dry_run,
            parts_db_rows=list(parts_db.values()),
            db_keys=db_keys,
        )
        if result is not None:
            new_rows.append(result)
            # Add to in-memory db so duplicates within one run are suppressed
            key = (result["value"], result["footprint"])
            db_keys.add(key)
            parts_db[key] = result

    # Write results
    if new_rows and not args.dry_run:
        # Merge: existing rows + new rows (new rows may overwrite if --force)
        merged: dict[tuple[str, str], dict[str, str]] = dict(parts_db)
        for row in new_rows:
            merged[(row["value"], row["footprint"])] = row
        write_parts_db(args.parts_db, list(merged.values()))
        print(f"\nWrote {len(new_rows)} new entry/entries to {args.parts_db}")
    elif new_rows and args.dry_run:
        print(f"\n(dry-run) Would add {len(new_rows)} entry/entries to {args.parts_db}")
    else:
        print("\nNo new entries to write.")


if __name__ == "__main__":
    main()
