# Thermal Logger

Hardware-agnostic thermal and power logger for Linux. Outputs wide-format CSV for baseline runs, curve derivation, and analysis.

## Requirements

- Linux (uses `/sys/class/hwmon`, `/sys/class/thermal`)
- Python 3.10+
- Optional: `lm-sensors` (`sensors`), `nvidia-smi` for GPU

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

Wide CSV: one row per poll, columns like `timestamp`, `hwmon0_nvme_temp1_input`, `thermal_thermal_zone0_INT3400_C`, `gpu_temp_C`, `gpu_power_W`, `cooling_cooling_device0_TFN1`, etc. Column names are derived from sysfs paths.

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
