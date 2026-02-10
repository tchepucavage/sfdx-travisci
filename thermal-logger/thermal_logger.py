#!/usr/bin/env python3
"""
Hardware-agnostic thermal logger for Linux.
Reads sysfs (hwmon, thermal), optional lm-sensors, optional nvidia-smi.
Outputs wide-format CSV for analysis and curve derivation.
"""

import argparse
import csv
import re
import subprocess
import sys
import time
from pathlib import Path


def read_sysfs(path: Path) -> float | None:
    """Read numeric value from sysfs, return None if missing or invalid."""
    try:
        raw = path.read_text().strip()
        return float(raw) if raw else None
    except (OSError, ValueError):
        return None


def discover_hwmon() -> dict[str, float]:
    """Read all hwmon temp and fan inputs."""
    out = {}
    hwmon = Path("/sys/class/hwmon")
    if not hwmon.exists():
        return out

    for dev in sorted(hwmon.iterdir()):
        name = read_sysfs(dev / "name")
        prefix = f"hwmon_{dev.name}"
        if name:
            prefix = f"{prefix}_{re.sub(r'[^a-zA-Z0-9]', '_', name)}"

        for f in dev.iterdir():
            if not f.is_file():
                continue
            if f.name == "power1_input":  # microwatts -> W
                val = read_sysfs(f)
                if val is not None:
                    out[f"{prefix}_power_W"] = round(val / 1_000_000, 3)
            elif "_input" in f.name:
                val = read_sysfs(f)
                if val is not None:
                    # hwmon temp/fan: temp in millidegrees, fan in RPM
                    if "temp" in f.name and val > 1000:
                        val = round(val / 1000, 2)  # mC -> C
                    col = f"{prefix}_{f.name.replace('_input', '')}"
                    out[col] = val

    return out


def discover_thermal_zones() -> dict[str, float]:
    """Read all thermal zone temps (millidegrees C -> C)."""
    out = {}
    thermal = Path("/sys/class/thermal")
    if not thermal.exists():
        return out

    for tz in sorted(thermal.glob("thermal_zone*")):
        type_path = tz / "type"
        temp_path = tz / "temp"
        if not temp_path.exists():
            continue
        val = read_sysfs(temp_path)
        if val is not None:
            type_name = read_sysfs(type_path) or tz.name
            col = f"thermal_{tz.name}_{re.sub(r'[^a-zA-Z0-9]', '_', type_name)}_C"
            out[col] = val / 1000  # mC -> C

    return out


def discover_cooling_devices() -> dict[str, float]:
    """Read current state of cooling devices (fans, throttling)."""
    out = {}
    thermal = Path("/sys/class/thermal")
    if not thermal.exists():
        return out

    for cd in sorted(thermal.glob("cooling_device*")):
        type_path = cd / "type"
        cur_path = cd / "cur_state"
        max_path = cd / "max_state"
        if not cur_path.exists():
            continue
        val = read_sysfs(cur_path)
        if val is not None:
            type_name = read_sysfs(type_path) or cd.name
            col = f"cooling_{cd.name}_{re.sub(r'[^a-zA-Z0-9]', '_', type_name)}"
            out[col] = val
            max_val = read_sysfs(max_path)
            if max_val and max_val > 0:
                out[f"{col}_pct"] = round(100 * val / max_val, 2)

    return out


def read_nvidia_smi() -> dict[str, float]:
    """Query nvidia-smi for GPU temp, power, utilization."""
    out = {}
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=temperature.gpu,power.draw,utilization.gpu,utilization.memory",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return out

        parts = [p.strip() for p in result.stdout.strip().split(",")]
        if len(parts) >= 1:
            try:
                out["gpu_temp_C"] = float(parts[0])
            except ValueError:
                pass
        if len(parts) >= 2:
            try:
                out["gpu_power_W"] = float(parts[1].replace(" W", "").strip())
            except ValueError:
                pass
        if len(parts) >= 3:
            try:
                out["gpu_util_pct"] = float(parts[2].replace("%", "").strip())
            except ValueError:
                pass
        if len(parts) >= 4:
            try:
                out["gpu_mem_util_pct"] = float(parts[3].replace("%", "").strip())
            except ValueError:
                pass
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return out


def read_lm_sensors() -> dict[str, float]:
    """Parse lm-sensors output if available (fallback/additional data)."""
    out = {}
    try:
        result = subprocess.run(
            ["sensors", "-j"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return out

        import json

        data = json.loads(result.stdout)
        for chip, entries in data.items():
            prefix = f"sensors_{re.sub(r'[^a-zA-Z0-9]', '_', chip)}"
            for label, vals in entries.items():
                if isinstance(vals, dict) and "input" in vals:
                    try:
                        v = float(vals["input"])
                        col = f"{prefix}_{re.sub(r'[^a-zA-Z0-9]', '_', label)}"
                        out[col] = v
                    except (ValueError, TypeError):
                        pass
    except (FileNotFoundError, subprocess.TimeoutExpired, ValueError):
        pass
    return out


def gather_row(use_lm_sensors: bool = True, use_nvidia: bool = True) -> dict[str, float]:
    """Gather one row of metrics from all available sources."""
    row = {}
    row.update(discover_hwmon())
    row.update(discover_thermal_zones())
    row.update(discover_cooling_devices())
    if use_nvidia:
        row.update(read_nvidia_smi())
    if use_lm_sensors:
        row.update(read_lm_sensors())
    return row


def get_ordered_columns(rows: list[dict]) -> list[str]:
    """Return column order: timestamp first, then stable sort of the rest."""
    if not rows:
        return ["timestamp"]
    cols: set[str] = set()
    for r in rows:
        cols.update(r.keys())
    others = sorted(cols - {"timestamp"})
    return ["timestamp"] + others


def main() -> None:
    parser = argparse.ArgumentParser(description="Thermal logger (wide CSV)")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("thermal_log.csv"),
        help="Output CSV path",
    )
    parser.add_argument(
        "-i",
        "--interval",
        type=float,
        default=5.0,
        help="Poll interval in seconds (default: 5)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run once and exit (for cron)",
    )
    parser.add_argument(
        "--no-lm-sensors",
        action="store_true",
        help="Skip lm-sensors (use sysfs only)",
    )
    parser.add_argument(
        "--no-nvidia",
        action="store_true",
        help="Skip nvidia-smi",
    )
    args = parser.parse_args()

    output = args.output
    write_header = not output.exists()
    rows_buffer: list[dict] = []

    def flush():
        nonlocal write_header
        if not rows_buffer:
            return
        columns = get_ordered_columns(rows_buffer)
        with output.open("a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
            if write_header:
                w.writeheader()
                write_header = False
            w.writerows(rows_buffer)
        rows_buffer.clear()

    try:
        while True:
            ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            row = gather_row(
                use_lm_sensors=not args.no_lm_sensors,
                use_nvidia=not args.no_nvidia,
            )
            row["timestamp"] = ts
            rows_buffer.append(row)
            flush()

            if args.once:
                break
            time.sleep(args.interval)
    except KeyboardInterrupt:
        pass
    finally:
        flush()


if __name__ == "__main__":
    main()
