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

## 2. Enable I2C on Raspberry Pi 5

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

If you run Proxmox on the Pi directly, make sure the I2C device nodes are available on the host (`/dev/i2c-1`) and not blocked by your platform configuration.

## 3. Install software dependencies

From this project directory:

```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-smbus
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt
```

Quick test of sensor readings:

```bash
python3 INA219.py
```

Press `Ctrl+C` to stop.

## 4. Configure MQTT publisher

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

## 5. Run as a systemd service

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
ExecStart=/usr/bin/python3 /workspaces/UPS-Module-3S-Proxmox-on-RP5/ups_mqtt_publisher.py
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

## 6. Home Assistant integration

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

## 7. MQTT verification

Use MQTT CLI on your broker host:

```bash
mosquitto_sub -h 192.168.1.10 -t 'ups/rpi5/#' -v
```

You should see:
- `ups/rpi5/availability online`
- periodic JSON payloads on `ups/rpi5/state`

## 8. Notes on battery percentage

`battery_percent` uses the same approximation as Waveshare demo:

$$
	ext{percent} = \text{clamp}\left(\frac{V_{bus} - 9.0}{3.6} \times 100, 0, 100\right)
$$

For high accuracy, tune this mapping to your specific cell chemistry and discharge curve.
