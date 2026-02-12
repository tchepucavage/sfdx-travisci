# Thermal Logger

Hardware-agnostic thermal and power logger for Linux. Outputs wide-format CSV for baseline runs, curve derivation, and analysis.

## Requirements

- Linux (uses `/sys/class/hwmon`, `/sys/class/thermal`)
- Python 3.10+
- Optional: `lm-sensors` (`sensors`), `nvidia-smi` for GPU

---

## Data Sources: What It Captures & How

The logger aggregates data from four sources. What appears in your CSV depends on your hardware and installed tools.

### 1. sysfs hwmon

**Path:** `/sys/class/hwmon/`

**What it is:** The Linux kernel exposes hardware monitors via the hwmon subsystem. Each directory (e.g. `hwmon0`, `hwmon1`) is a physical chip—CPU sensors, motherboard sensors, NVMe drives, etc.—that reports temps, fans, and sometimes power.

**How it's read:** The logger walks all `hwmon*` devices, reads their `name` file, then scans for `*_input` files and `power1_input`.

**Values captured:**

| Source file      | Example column name           | Units  | Notes |
|------------------|-------------------------------|--------|-------|
| `temp*_input`    | `hwmon0_nvme_temp1_input`     | °C     | Raw value is millidegrees; values &gt;1000 are divided by 1000 |
| `fan*_input`     | `hwmon1_fan1_input`           | RPM    | Fan speed as reported by the hardware |
| `power1_input`   | `hwmon0_nvme_power_W`         | W      | Raw value is microwatts; divided by 1,000,000 |

**Column naming:** `hwmon_{device}_{name}_{sensor}` — e.g. `hwmon0_coretemp_temp1_input`. The `name` comes from the device’s `name` file (sanitized for CSV).

---

### 2. sysfs thermal zones

**Path:** `/sys/class/thermal/thermal_zone*`

**What it is:** Linux thermal framework zones—high-level abstractions of thermal sensors. Typically wired to CPU package, AC exposed metal (INT3400), or platform-specific zones.

**How it's read:** For each `thermal_zone*`, the logger reads `type` (human label) and `temp` (raw value).

**Values captured:**

| Source file | Example column name                    | Units | Notes |
|-------------|----------------------------------------|-------|-------|
| `temp`      | `thermal_thermal_zone0_INT3400_C`       | °C    | Raw value is millidegrees C; divided by 1000 |

**Column naming:** `thermal_{zone}_{type}_C` — e.g. `thermal_thermal_zone0_x86_pkg_temp_C`.

---

### 3. sysfs cooling devices

**Path:** `/sys/class/thermal/cooling_device*`

**What it is:** Cooling actuators—fans, thermal throttling, etc.—exposed by the thermal framework. `cur_state` is the current level, `max_state` is the maximum.

**How it's read:** For each `cooling_device*`, reads `type`, `cur_state`, and `max_state`.

**Values captured:**

| Source file   | Example column name        | Units   | Notes |
|---------------|----------------------------|---------|-------|
| `cur_state`   | `cooling_cooling_device0_TFN1` | level   | Current cooling state (0 = off, max = full) |
| derived       | `cooling_cooling_device0_TFN1_pct` | %   | `cur_state / max_state * 100` |

**Column naming:** `cooling_{device}_{type}` and `{same}_pct` for percentage.

---

### 4. nvidia-smi (GPU)

**Command:** `nvidia-smi --query-gpu=... --format=csv,noheader,nounits`

**What it is:** NVIDIA’s tool for querying GPU status. Only used when NVIDIA GPUs are present.

**How it's read:** Subprocess call, CSV output parsed line-by-line.

**Values captured:**

| Query field           | Column name        | Units | Notes |
|-----------------------|--------------------|-------|-------|
| `temperature.gpu`     | `gpu_temp_C`       | °C    | Die temperature |
| `power.draw`          | `gpu_power_W`      | W     | Instantaneous power draw |
| `utilization.gpu`     | `gpu_util_pct`     | %     | GPU compute utilization |
| `utilization.memory`  | `gpu_mem_util_pct` | %     | Memory controller utilization |

**Availability:** Skipped if `nvidia-smi` is not installed or times out. Use `--no-nvidia` to disable.

---

### 5. lm-sensors (sensors)

**Command:** `sensors -j` (JSON output)

**What it is:** User-space tool that reads various sensor chips (e.g. via I2C/SMBus). Often reports motherboard temps, voltage, and fans that may not appear in hwmon or thermal zones.

**How it's read:** Subprocess call; JSON is parsed for chip name, label, and `input` value.

**Values captured:** All sensor inputs from the JSON: temps, voltages, fans, etc., as reported by each chip.

**Column naming:** `sensors_{chip}_{label}` — e.g. `sensors_coretemp_Core_0`, `sensors_nvme_nvme_temp1`.

**Availability:** Skipped if `sensors` is not installed. Use `--no-lm-sensors` to disable.

---

## Column quick reference

| Column pattern | Source | Meaning | Units |
|----------------|--------|---------|-------|
| `timestamp` | logger | ISO 8601 UTC | — |
| `gpu_temp_C` | nvidia-smi | GPU die temperature | °C |
| `gpu_power_W` | nvidia-smi | GPU power draw | W |
| `gpu_util_pct` | nvidia-smi | GPU compute utilization | % |
| `gpu_mem_util_pct` | nvidia-smi | GPU memory utilization | % |
| `hwmon_{dev}_{chip}_{sensor}` | sysfs hwmon | Temp, fan RPM, or power from chip | °C, RPM, or W |
| `thermal_{zone}_{type}_C` | sysfs thermal | Zone temperature (type = INT3400_Thermal, x86_pkg_temp, etc.) | °C |
| `cooling_{dev}_{type}` | sysfs cooling | Cooling device current state (type = Processor, TFN1, etc.) | level |
| `cooling_{dev}_{type}_pct` | sysfs cooling | Cooling level as % of max | % |
| `sensors_{chip}_{label}` | lm-sensors | Chip sensor (temp, voltage, fan) | varies |

## Source overlap

- **hwmon vs thermal zones:** Some temps appear in both. hwmon comes from raw hardware monitors; thermal zones are the kernel’s thermal model. Both are useful for cross-checking.
- **hwmon vs lm-sensors:** lm-sensors often uses the same underlying chips as hwmon; you may see similar values with different names. lm-sensors can add labels and formatting that hwmon does not.
- **GPU:** nvidia-smi is the primary source for NVIDIA GPU temp and power; sysfs hwmon/thermal rarely expose GPU sensors directly.

## Usage

```bash
# Continuous logging, 5s interval, default output thermal_log.csv
./thermal_logger.py

# Once (for cron)
./thermal_logger.py --once

# Custom interval and output
./thermal_logger.py -i 1 -o /var/log/thermal.csv

# Sysfs only (no lm-sensors, no nvidia-smi)
./thermal_logger.py --no-lm-sensors --no-nvidia
```

## Output

Wide CSV: one row per poll. Column names are derived from each source (see [Data Sources](#data-sources-what-it-captures--how) above). Examples:

- `timestamp`
- `hwmon0_nvme_temp1_input`, `hwmon1_coretemp_temp1_input`
- `thermal_thermal_zone0_INT3400_C`, `thermal_thermal_zone1_x86_pkg_temp_C`
- `cooling_cooling_device0_TFN1`, `cooling_cooling_device0_TFN1_pct`
- `gpu_temp_C`, `gpu_power_W`, `gpu_util_pct`, `gpu_mem_util_pct`
- `sensors_coretemp_Core_0`, etc.

## Cron Example

```cron
*/1 * * * * /opt/thermal-logger/thermal_logger.py --once -o /var/log/thermal.csv
```

## systemd Service

Create `/etc/systemd/system/thermal-logger.service`:

```ini
[Unit]
Description=Thermal logger
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 /opt/thermal-logger/thermal_logger.py -i 5 -o /var/log/thermal.csv
Restart=on-failure

[Install]
WantedBy=multi-user.target
```
