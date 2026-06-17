#!/usr/bin/env python3
"""Sync LCSC Part numbers from the OVERRIDES dict into the KiCad schematic.

Reads tools/build_jlcpcb_bom.py::OVERRIDES and writes (or updates) the
"LCSC Part" property on every matching symbol in smart_pouch.kicad_sch.
The schematic is the single source of truth afterwards; the BOM tool reads
LCSC Part numbers from the CSV export instead of the hardcoded dict.

Usage:
    python3 tools/sync_lcsc_to_sch.py [--dry-run]
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Bootstrap: make tools/ importable so we can reuse OVERRIDES and expand_refs
# ---------------------------------------------------------------------------
TOOLS_DIR = Path(__file__).parent
REPO_ROOT = TOOLS_DIR.parent
sys.path.insert(0, str(TOOLS_DIR))

from build_jlcpcb_bom import OVERRIDES, expand_refs  # noqa: E402

SCH_PATH = REPO_ROOT / "smart_pouch.kicad_sch"
BAK_PATH = REPO_ROOT / "smart_pouch.kicad_sch.bak"

# ---------------------------------------------------------------------------
# Template for a new LCSC Part property block (two-tab indent to match file)
# ---------------------------------------------------------------------------
LCSC_PROP_TEMPLATE = """\t\t(property "LCSC Part" "{value}"
\t\t\t(at 0 0 0)
\t\t\t(hide yes)
\t\t\t(show_name no)
\t\t\t(do_not_autoplace no)
\t\t\t(effects
\t\t\t\t(font
\t\t\t\t\t(size 1.27 1.27)
\t\t\t\t)
\t\t\t)
\t\t)"""

# Pattern to match a property block (name, value, and everything up to closing paren).
# We match greedily on the inner content but lazily so we don't bleed across properties.
PROP_PATTERN = re.compile(
    r'(\t*)\(property\s+"([^"]+)"\s+"([^"]*)"\s*([\s\S]*?)\n\1\)',
    re.MULTILINE,
)


def find_symbol_spans(text: str) -> list[tuple[int, int]]:
    """Return (start, end) byte offsets of every top-level symbol block.

    A 'symbol' here means the (symbol ...) block that starts with exactly one
    tab (instance-level symbols in .kicad_sch, not library definitions).
    We detect boundaries by finding lines that start with '\t(symbol' and
    matching the closing paren at the same indent level.
    """
    spans: list[tuple[int, int]] = []
    pos = 0
    while True:
        # Find next "\t(symbol" that is NOT inside a library section
        idx = text.find("\n\t(symbol\n", pos)
        if idx == -1:
            break
        start = idx + 1  # skip the leading \n; start at the \t
        # Walk forward counting parens to find the matching close
        depth = 0
        i = start
        n = len(text)
        while i < n:
            c = text[i]
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    spans.append((start, i + 1))
                    break
            i += 1
        pos = start + 1
    return spans


def get_reference(block: str) -> str | None:
    """Extract the Reference property value from a symbol block."""
    m = re.search(r'\(property\s+"Reference"\s+"([^"]+)"', block)
    return m.group(1) if m else None


def get_lcsc_value(block: str) -> str | None:
    """Return current LCSC Part value, or None if property is absent."""
    m = re.search(r'\(property\s+"LCSC Part"\s+"([^"]*)"', block)
    return m.group(1) if m else None


def update_lcsc_value(block: str, new_value: str) -> str:
    """Replace the value in an existing LCSC Part property."""
    return re.sub(
        r'(\(property\s+"LCSC Part"\s+")[^"]*(")',
        lambda m: m.group(1) + new_value + m.group(2),
        block,
        count=1,
    )


def insert_lcsc_property(block: str, new_value: str) -> str:
    """Insert an LCSC Part property before the first (pin ...) or (instances ...) line."""
    new_prop = LCSC_PROP_TEMPLATE.format(value=new_value)
    # Insert before the first (pin or (instances line (both use two-tab indent)
    insert_re = re.compile(r"(\t\t\((?:pin|instances)\b)")
    m = insert_re.search(block)
    if m:
        return block[: m.start()] + new_prop + "\n" + block[m.start() :]
    # Fallback: insert before closing paren of the symbol block
    last_close = block.rfind("\n\t)")
    if last_close != -1:
        return block[: last_close] + "\n" + new_prop + block[last_close :]
    return block + "\n" + new_prop


def build_ref_to_lcsc(overrides: dict) -> dict[str, str]:
    """Expand OVERRIDES keys into per-designator {ref: lcsc} mapping.

    When the same ref appears in multiple keys (overlapping groups), the last
    entry wins (same as dict iteration order in CPython 3.7+).
    """
    result: dict[str, str] = {}
    for key, override in overrides.items():
        if not override.lcsc:
            continue
        for ref in expand_refs(key):
            result[ref] = override.lcsc
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync LCSC Part numbers into the KiCad schematic.")
    parser.add_argument("--dry-run", action="store_true", help="Print changes without writing the file.")
    args = parser.parse_args()

    ref_to_lcsc = build_ref_to_lcsc(OVERRIDES)
    print(f"OVERRIDES expanded to {len(ref_to_lcsc)} individual designators.")

    text = SCH_PATH.read_text(encoding="utf-8")
    spans = find_symbol_spans(text)
    print(f"Found {len(spans)} symbol blocks in {SCH_PATH.name}.")

    # Build a mapping from reference → list of span indices
    ref_to_spans: dict[str, list[int]] = {}
    for i, (start, end) in enumerate(spans):
        block = text[start:end]
        ref = get_reference(block)
        if ref:
            ref_to_spans.setdefault(ref, []).append(i)

    # Apply updates
    # We collect (span_index, new_block) pairs, then rebuild the text in one pass.
    updates: list[tuple[int, str]] = []
    stats = {"set": 0, "updated": 0, "already_correct": 0, "not_found": 0}

    for ref, lcsc in sorted(ref_to_lcsc.items()):
        span_indices = ref_to_spans.get(ref)
        if not span_indices:
            print(f"  WARNING: {ref} not found in schematic.")
            stats["not_found"] += 1
            continue
        for si in span_indices:
            start, end = spans[si]
            block = text[start:end]
            current = get_lcsc_value(block)
            if current is None:
                new_block = insert_lcsc_property(block, lcsc)
                updates.append((si, new_block))
                action = "INSERT"
                stats["set"] += 1
            elif current == lcsc:
                stats["already_correct"] += 1
                action = "OK"
            else:
                new_block = update_lcsc_value(block, lcsc)
                updates.append((si, new_block))
                action = "UPDATE"
                stats["updated"] += 1
            if action != "OK":
                print(f"  {action:8s} {ref}: {current!r} → {lcsc!r}")

    print(
        f"\nSummary: {stats['set']} inserted, {stats['updated']} updated, "
        f"{stats['already_correct']} already correct, {stats['not_found']} not found in schematic."
    )

    if not updates:
        print("Nothing to write.")
        return

    if args.dry_run:
        print("Dry-run mode — no files written.")
        return

    # Build replacement dict indexed by span index
    update_map: dict[int, str] = dict(updates)

    # Rebuild text by splicing in updated blocks (iterate spans in reverse to preserve offsets)
    parts: list[str] = []
    prev_end = len(text)
    for i in range(len(spans) - 1, -1, -1):
        start, end = spans[i]
        parts.append(text[end:prev_end])
        if i in update_map:
            parts.append(update_map[i])
        else:
            parts.append(text[start:end])
        prev_end = start
    parts.append(text[:prev_end])
    new_text = "".join(reversed(parts))

    # Backup before writing
    if not BAK_PATH.exists():
        shutil.copy2(SCH_PATH, BAK_PATH)
        print(f"Backup written to {BAK_PATH.name}")
    else:
        print(f"Backup already exists at {BAK_PATH.name} — not overwriting.")

    SCH_PATH.write_text(new_text, encoding="utf-8")
    print(f"Schematic written: {SCH_PATH}")


if __name__ == "__main__":
    main()
