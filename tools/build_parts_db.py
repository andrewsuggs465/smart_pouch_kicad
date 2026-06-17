#!/usr/bin/env python3
"""One-shot extraction: convert OVERRIDES dict in build_jlcpcb_bom.py to bom/parts_db.csv.

Join each OVERRIDES entry with the raw KiCad BOM to get the value+footprint key.
Run once to seed parts_db.csv, then maintain parts_db.csv directly.
"""

from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Inline copies of helpers needed to expand ref ranges without importing the
# full build script (which has side effects on import in older versions).
# ---------------------------------------------------------------------------

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
        expanded.extend(f"{prefix}{n}" for n in range(start_ref[1], end_ref[1] + 1))
    return expanded


def read_raw_bom(path: Path) -> dict[str, dict[str, str]]:
    """Return a mapping from every individual ref (e.g. 'C1') to its raw row."""
    ref_to_row: dict[str, dict[str, str]] = {}
    with path.open(newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            refs_field = row.get("Refs", row.get("Reference", ""))
            for ref in expand_refs(refs_field):
                ref_to_row[ref] = row
    return ref_to_row


def main() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    raw_bom_path = repo_root / "bom" / "smart_pouch_kicad_bom_raw.csv"
    out_path = repo_root / "bom" / "parts_db.csv"

    if not raw_bom_path.exists():
        print(f"ERROR: raw BOM not found at {raw_bom_path}", file=sys.stderr)
        sys.exit(1)

    ref_to_row = read_raw_bom(raw_bom_path)

    # Import OVERRIDES from the build script.
    sys.path.insert(0, str(repo_root / "tools"))
    from build_jlcpcb_bom import OVERRIDES  # noqa: PLC0415

    output_rows: list[dict[str, str]] = []
    seen_keys: set[tuple[str, str]] = set()

    for refs_key, override in OVERRIDES.items():
        # Determine value and footprint from the raw BOM.
        # Use the first individual ref to look up the row.
        individual_refs = expand_refs(refs_key)
        if not individual_refs:
            print(f"WARNING: could not expand refs '{refs_key}', skipping", file=sys.stderr)
            continue

        raw_row = ref_to_row.get(individual_refs[0])
        if raw_row is None:
            print(f"WARNING: ref '{individual_refs[0]}' from key '{refs_key}' not found in raw BOM", file=sys.stderr)
            continue

        value = raw_row.get("Value", "").strip()
        # Use the override footprint if one was specified; otherwise use the raw footprint.
        footprint = override.footprint.strip() if override.footprint else raw_row.get("Footprint", "").strip()

        key = (value.lower(), footprint)
        if key in seen_keys:
            # Duplicate (value, footprint) pair — two OVERRIDES entries resolve to the same key.
            # Both have the same LCSC (e.g. "C7,C16,C18,C20-C23" and "C16,C18" both map to C15850).
            # Skip the duplicate silently.
            continue
        seen_keys.add(key)

        output_rows.append(
            {
                "value": value,
                "footprint": footprint,
                "lcsc": override.lcsc,
                "manufacturer": override.manufacturer,
                "mpn": override.mpn,
                "note": override.note,
            }
        )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["value", "footprint", "lcsc", "manufacturer", "mpn", "note"])
        writer.writeheader()
        writer.writerows(output_rows)

    print(f"Wrote {out_path} ({len(output_rows)} entries)")


if __name__ == "__main__":
    main()
