#!/usr/bin/env python3
"""Convert HWiNFO PORTAL.csv to MVP-compatible format."""

import csv
import re
from pathlib import Path

def sanitize_header(name):
    """Make header safe for CSV and unique."""
    return re.sub(r'[^\w\s\-.#%°]', '', name).strip() or 'col'

def parse_value(val):
    """Parse value to float, return None if not numeric."""
    if val is None or val == '':
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None

def main():
    src = Path(__file__).parent / "PORTAL.csv"
    dst = Path(__file__).parent / "PORTAL_mvp.csv"

    with open(src, encoding="utf-8", errors="replace") as f:
        reader = csv.reader(f)
        row1 = next(reader)  # component names - skip
        row2 = next(reader)  # metric names - use as headers

    # Build unique headers (row2 has duplicates)
    seen = {}
    headers = []
    for i, h in enumerate(row2):
        base = sanitize_header(h) or f"col_{i}"
        if base in seen:
            seen[base] += 1
            unique = f"{base}_{seen[base]}"
        else:
            seen[base] = 0
            unique = base
        headers.append(unique)

    # Map PORTAL columns to MVP-friendly aliases for reward computation
    alias_patterns = [
        ("Cores (Max) Temperature", "cpuTemp"),
        ("Package Power [W]", "power"),
        ("FANIN1 Rotation Speed", "fanSpeed"),  # RPM
    ]
    alias_indices = {}
    for pattern, alias in alias_patterns:
        for i, h in enumerate(row2):
            if pattern in (h or ""):
                alias_indices[alias] = i
                break

    # Read data
    rows = []
    with open(src, encoding="utf-8", errors="replace") as f:
        reader = csv.reader(f)
        next(reader)
        next(reader)
        for row in reader:
            if len(row) < len(headers):
                row.extend([""] * (len(headers) - len(row)))
            rows.append(row[:len(headers)])

    # Build output: only columns where EVERY row is numeric
    numeric_cols = []
    for col_idx in range(len(headers)):
        values = [parse_value(rows[r][col_idx]) for r in range(len(rows))]
        if all(v is not None and v == v for v in values):  # no None, no NaN
            numeric_cols.append((col_idx, headers[col_idx]))

    if len(numeric_cols) < 2:
        print("Error: Need at least 2 fully numeric columns. Found:", len(numeric_cols))
        return

    # Output headers = kept column names + aliases
    out_headers = [h for _, h in numeric_cols]

    # Add MVP aliases if source columns exist and aren't already included
    for alias, idx in alias_indices.items():
        if alias not in out_headers and idx < len(headers):
            # Check if this column is in numeric_cols
            for col_idx, h in numeric_cols:
                if col_idx == idx:
                    # Use the existing header; MVP won't match. Add alias as extra column.
                    break
            else:
                # Column at idx - check if numeric
                values = [parse_value(rows[r][idx]) for r in range(len(rows))]
                if all(v is not None and v == v for v in values):
                    out_headers.append(alias)
                    # We'll add the data when writing
                    break

    # Simpler: add alias columns by copying from source
    alias_col_indices = {}  # alias -> source col_idx in numeric_cols
    for alias, src_idx in alias_indices.items():
        for col_idx, h in numeric_cols:
            if col_idx == src_idx:
                alias_col_indices[alias] = col_idx
                break

    # Write output
    with open(dst, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(out_headers)

        for row in rows:
            out_row = []
            for col_idx, h in numeric_cols:
                val = parse_value(row[col_idx])
                out_row.append(val if val is not None else "")

            # Append alias columns (duplicate values with MVP-friendly names)
            for alias in ["cpuTemp", "power", "fanSpeed"]:
                if alias in alias_col_indices:
                    idx = alias_col_indices[alias]
                    val = parse_value(row[idx])
                    out_row.append(val if val is not None else "")

        # Fix: we need to add aliases to out_headers and out_row
        pass

    # Rebuild: out_headers should include alias names, out_row should have alias values
    final_headers = [h for _, h in numeric_cols]
    for alias in ["cpuTemp", "power", "fanSpeed"]:
        if alias in alias_col_indices:
            final_headers.append(alias)

    with open(dst, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(final_headers)

        for row in rows:
            out_row = []
            for col_idx, h in numeric_cols:
                val = parse_value(row[col_idx])
                out_row.append(val if val is not None else "")

            for alias in ["cpuTemp", "power", "fanSpeed"]:
                if alias in alias_col_indices:
                    idx = alias_col_indices[alias]
                    val = parse_value(row[idx])
                    out_row.append(val if val is not None else "")

            writer.writerow(out_row)

    print(f"Wrote {dst}")
    print(f"  Rows: {len(rows)}")
    print(f"  Columns: {len(final_headers)}")
    print(f"  MVP aliases: cpuTemp, power, fanSpeed")

if __name__ == "__main__":
    main()
