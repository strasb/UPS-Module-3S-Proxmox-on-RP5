# Waveshare UPS 3S on Raspberry Pi 5 with MQTT and Home Assistant

This has to be run in an LXC container and confirm working with debian_13_trixie_arm64_default.tar.xz
from https://github.com/oneclickvirt/lxc_arm_images/releases/tag/debian

This repository provides a practical integration for the Waveshare UPS Module 3S (INA219 over I2C) on Raspberry Pi 5.

It includes:
- INA219 reader (`INA219.py`)
- MQTT telemetry publisher (`ups_mqtt_publisher.py`)
- Home Assistant MQTT discovery support (automatic entities)

## 1. Hardware and safety

Required hardware:
- Waveshare UPS Module 3S
- Raspberry Pi 5
- 3x matched 18650 cells (same model/age/capacity)
- 12.6V 2A charger for UPS charging input

GPIO wiring:

| UPS 3S | Raspberry Pi 5 |
|---|---|
| 5V | 5V |
| GND | GND |
| SCL | SCL (GPIO3, pin 5) |
| SDA | SDA (GPIO2, pin 3) |

Important safety notes:
- Use only healthy matched cells.
- Verify battery polarity before charging.
- Use a 12.6V charger for charging the UPS battery pack.
- Keep the insulating board in place to avoid shorts.

## 2. Enable I2C on Raspberry Pi 5 / Proxmox host

On Raspberry Pi OS:

```bash
sudo raspi-config
```

Then enable:
- Interface Options -> I2C -> Yes

Reboot:

```bash
sudo reboot
```

Verify INA219 is visible on bus 1:

```bash
sudo apt update
sudo apt install -y i2c-tools
i2cdetect -y 1
```

Expected address for this UPS demo is usually `0x41`.

If you run Proxmox on the Pi directly, make sure the I2C device nodes are available on the host:

```bash
ls -l /dev/i2c-*
i2cdetect -l
```

Typical output on Raspberry Pi 5 / Proxmox may include buses such as `/dev/i2c-1`, `/dev/i2c-13`, and `/dev/i2c-14`.

## 3. Minimal Proxmox LXC setup for I2C access

Create a small privileged Debian LXC and pass only the required I2C device(s) into it.

Recommended container sizing:
- 1 vCPU
- 256-512 MB RAM
- 4 GB disk
- Privileged container

Example `/etc/pve/lxc/<CTID>.conf` entries:

```ini
lxc.cgroup2.devices.allow: c 89:* rwm
lxc.mount.entry: /dev/i2c-1 dev/i2c-1 none bind,optional,create=file
lxc.mount.entry: /dev/i2c-13 dev/i2c-13 none bind,optional,create=file
lxc.mount.entry: /dev/i2c-14 dev/i2c-14 none bind,optional,create=file
```

If you only need one bus, keep only that line, for example `/dev/i2c-1`.

Restart the container after editing the config:

```bash
pct stop <CTID>
pct start <CTID>
```

Then enter the container and verify:

```bash
pct enter <CTID>
ls -l /dev/i2c-*
i2cdetect -l
i2cdetect -y 1
```

Notes:
- In an LXC, `/sys` is restricted and host hardware sysfs entries are read-only.
- Errors such as `Failed to write 'change' ... Read-only file system` are expected if a tool tries to trigger udev/sysfs changes from inside the container.
- Normal I2C access through `/dev/i2c-*` should still work.

## 4. Install software dependencies

From this project directory inside the LXC:

```bash
sudo apt update
sudo apt install -y python3-full python3-venv python3-pip python3-smbus i2c-tools
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

This uses a virtual environment, which is the recommended approach on Debian 12/13 and Proxmox LXC because system Python is externally managed (PEP 668).

If you see an error like `externally-managed-environment`, do not install packages globally with `pip` unless you explicitly want to override Debian's protections.

Quick test of sensor readings:

```bash
. .venv/bin/activate
python3 INA219.py
```

Press `Ctrl+C` to stop.

## 5. Configure MQTT publisher

`ups_mqtt_publisher.py` publishes JSON telemetry and availability topics.

Default topics:
- State: `ups/rpi5/state`
- Availability: `ups/rpi5/availability`

Default metrics in state JSON:
- `bus_voltage_v`
- `shunt_voltage_v`
- `psu_voltage_v`
- `current_a`
- `power_w`
- `battery_percent`
- `timestamp`

Run manually:

```bash
. .venv/bin/activate
python3 ups_mqtt_publisher.py \
	--mqtt-host 192.168.1.10 \
	--mqtt-port 1883 \
	--mqtt-username homeassistant \
	--mqtt-password your_password \
	--mqtt-topic ups/rpi5 \
	--i2c-bus 1 \
	--ina219-addr 0x41 \
	--poll-interval 15
```

Environment variables are also supported:
- `MQTT_HOST`, `MQTT_PORT`, `MQTT_USERNAME`, `MQTT_PASSWORD`
- `MQTT_TOPIC`, `POLL_INTERVAL`
- `I2C_BUS`, `INA219_ADDR`
- `HA_DISCOVERY` (`1` or `0`)
- `HA_DISCOVERY_PREFIX` (default `homeassistant`)
- `DEVICE_ID`

## 6. Run as a systemd service

Create service file:

```bash
sudo tee /etc/systemd/system/ups-mqtt.service >/dev/null <<'EOF'
[Unit]
Description=Waveshare UPS 3S MQTT Publisher
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=/workspaces/UPS-Module-3S-Proxmox-on-RP5
Environment=MQTT_HOST=192.168.1.10
Environment=MQTT_PORT=1883
Environment=MQTT_USERNAME=homeassistant
Environment=MQTT_PASSWORD=your_password
Environment=MQTT_TOPIC=ups/rpi5
Environment=POLL_INTERVAL=15
Environment=I2C_BUS=1
Environment=INA219_ADDR=0x41
Environment=HA_DISCOVERY=1
ExecStart=/workspaces/UPS-Module-3S-Proxmox-on-RP5/.venv/bin/python /workspaces/UPS-Module-3S-Proxmox-on-RP5/ups_mqtt_publisher.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now ups-mqtt.service
sudo systemctl status ups-mqtt.service
```

View logs:

```bash
journalctl -u ups-mqtt.service -f
```

## 7. Home Assistant integration

### Option A: MQTT discovery (recommended)

If MQTT integration is already enabled in Home Assistant and `HA_DISCOVERY=1`, entities are created automatically under device name `Waveshare UPS 3S`.

Published discovery entities:
- Bus Voltage
- PSU Voltage
- Current
- Power
- Battery

### Option B: Manual YAML sensors

If discovery is disabled, add this to `configuration.yaml`:

```yaml
mqtt:
  sensor:
    - name: "UPS Bus Voltage"
      unique_id: ups_bus_voltage
      state_topic: "ups/rpi5/state"
      unit_of_measurement: "V"
      device_class: voltage
      value_template: "{{ value_json.bus_voltage_v }}"

    - name: "UPS PSU Voltage"
      unique_id: ups_psu_voltage
      state_topic: "ups/rpi5/state"
      unit_of_measurement: "V"
      device_class: voltage
      value_template: "{{ value_json.psu_voltage_v }}"

    - name: "UPS Current"
      unique_id: ups_current
      state_topic: "ups/rpi5/state"
      unit_of_measurement: "A"
      device_class: current
      value_template: "{{ value_json.current_a }}"

    - name: "UPS Power"
      unique_id: ups_power
      state_topic: "ups/rpi5/state"
      unit_of_measurement: "W"
      device_class: power
      value_template: "{{ value_json.power_w }}"

    - name: "UPS Battery"
      unique_id: ups_battery
      state_topic: "ups/rpi5/state"
      unit_of_measurement: "%"
      device_class: battery
      value_template: "{{ value_json.battery_percent }}"
```

After editing YAML, restart Home Assistant.

## 8. MQTT verification

Use MQTT CLI on your broker host:

```bash
mosquitto_sub -h 192.168.1.10 -t 'ups/rpi5/#' -v
```

You should see:
- `ups/rpi5/availability online`
- periodic JSON payloads on `ups/rpi5/state`

## 9. Notes on battery percentage

`battery_percent` uses the same approximation as Waveshare demo:

$$
\text{percent} = \text{clamp}\left(\frac{V_{bus} - 9.0}{3.6} \times 100, 0, 100\right)
$$

For high accuracy, tune this mapping to your specific cell chemistry and discharge curve.
