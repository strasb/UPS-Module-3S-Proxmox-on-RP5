#!/usr/bin/env python3
"""Publish Waveshare UPS 3S telemetry to MQTT for Home Assistant."""

import argparse
import json
import os
import signal
import socket
import sys
import time
from typing import Dict

import paho.mqtt.client as mqtt

from INA219 import INA219


RUNNING = True


def _load_env_defaults() -> Dict[str, str]:
    return {
        "MQTT_HOST": os.getenv("MQTT_HOST", "127.0.0.1"),
        "MQTT_PORT": os.getenv("MQTT_PORT", "1883"),
        "MQTT_USERNAME": os.getenv("MQTT_USERNAME", ""),
        "MQTT_PASSWORD": os.getenv("MQTT_PASSWORD", ""),
        "MQTT_TOPIC": os.getenv("MQTT_TOPIC", "ups/rpi5"),
        "POLL_INTERVAL": os.getenv("POLL_INTERVAL", "15"),
        "I2C_BUS": os.getenv("I2C_BUS", "1"),
        "INA219_ADDR": os.getenv("INA219_ADDR", "0x41"),
        "HA_DISCOVERY": os.getenv("HA_DISCOVERY", "1"),
        "HA_DISCOVERY_PREFIX": os.getenv("HA_DISCOVERY_PREFIX", "homeassistant"),
        "DEVICE_ID": os.getenv("DEVICE_ID", f"rpi5_ups_{socket.gethostname()}"),
    }


def _signal_handler(_sig, _frame):
    global RUNNING
    RUNNING = False


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def build_payload(ina219: INA219) -> Dict[str, float]:
    bus_voltage = ina219.getBusVoltage_V()
    shunt_voltage = ina219.getShuntVoltage_mV() / 1000.0
    current_a = ina219.getCurrent_mA() / 1000.0
    power_w = ina219.getPower_W()
    charge_pct = clamp((bus_voltage - 9.0) / 3.6 * 100.0, 0.0, 100.0)

    return {
        "bus_voltage_v": round(bus_voltage, 3),
        "shunt_voltage_v": round(shunt_voltage, 6),
        "psu_voltage_v": round(bus_voltage + shunt_voltage, 3),
        "current_a": round(current_a, 3),
        "power_w": round(power_w, 3),
        "battery_percent": round(charge_pct, 1),
        "timestamp": int(time.time()),
    }


def publish_discovery(
    client: mqtt.Client,
    prefix: str,
    device_id: str,
    state_topic: str,
    availability_topic: str,
):
    device = {
        "identifiers": [device_id],
        "name": "Waveshare UPS 3S",
        "manufacturer": "Waveshare",
        "model": "UPS Module 3S",
    }

    sensors = [
        ("bus_voltage", "Bus Voltage", "bus_voltage_v", "V", "voltage", "measurement"),
        ("psu_voltage", "PSU Voltage", "psu_voltage_v", "V", "voltage", "measurement"),
        ("current", "Current", "current_a", "A", "current", "measurement"),
        ("power", "Power", "power_w", "W", "power", "measurement"),
        (
            "battery",
            "Battery",
            "battery_percent",
            "%",
            "battery",
            "measurement",
        ),
    ]

    for object_id, name, key, unit, device_class, state_class in sensors:
        topic = f"{prefix}/sensor/{device_id}_{object_id}/config"
        payload = {
            "name": name,
            "unique_id": f"{device_id}_{object_id}",
            "state_topic": state_topic,
            "availability_topic": availability_topic,
            "payload_available": "online",
            "payload_not_available": "offline",
            "value_template": f"{{{{ value_json.{key} }}}}",
            "device": device,
            "unit_of_measurement": unit,
            "device_class": device_class,
            "state_class": state_class,
        }
        client.publish(topic, json.dumps(payload), qos=1, retain=True)


def parse_args(defaults: Dict[str, str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Waveshare UPS 3S MQTT publisher")
    parser.add_argument("--mqtt-host", default=defaults["MQTT_HOST"])
    parser.add_argument("--mqtt-port", type=int, default=int(defaults["MQTT_PORT"]))
    parser.add_argument("--mqtt-username", default=defaults["MQTT_USERNAME"])
    parser.add_argument("--mqtt-password", default=defaults["MQTT_PASSWORD"])
    parser.add_argument("--mqtt-topic", default=defaults["MQTT_TOPIC"])
    parser.add_argument("--poll-interval", type=int, default=int(defaults["POLL_INTERVAL"]))
    parser.add_argument("--i2c-bus", type=int, default=int(defaults["I2C_BUS"]))
    parser.add_argument("--ina219-addr", type=lambda x: int(x, 0), default=int(defaults["INA219_ADDR"], 0))
    parser.add_argument("--ha-discovery", action="store_true", default=defaults["HA_DISCOVERY"] == "1")
    parser.add_argument("--no-ha-discovery", action="store_true")
    parser.add_argument("--ha-discovery-prefix", default=defaults["HA_DISCOVERY_PREFIX"])
    parser.add_argument("--device-id", default=defaults["DEVICE_ID"])
    return parser.parse_args()


def main() -> int:
    defaults = _load_env_defaults()
    args = parse_args(defaults)

    if args.no_ha_discovery:
        args.ha_discovery = False

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    availability_topic = f"{args.mqtt_topic}/availability"
    state_topic = f"{args.mqtt_topic}/state"

    client_id = f"ups3s-{socket.gethostname()}"
    client = mqtt.Client(client_id=client_id, clean_session=True)
    client.will_set(availability_topic, payload="offline", qos=1, retain=True)

    if args.mqtt_username:
        client.username_pw_set(args.mqtt_username, args.mqtt_password)

    try:
        ina219 = INA219(i2c_bus=args.i2c_bus, addr=args.ina219_addr)
    except Exception as exc:
        print(f"Failed to initialize INA219: {exc}", file=sys.stderr)
        return 1

    try:
        client.connect(args.mqtt_host, args.mqtt_port, keepalive=60)
        client.loop_start()
    except Exception as exc:
        print(f"Failed to connect MQTT broker: {exc}", file=sys.stderr)
        return 1

    client.publish(availability_topic, payload="online", qos=1, retain=True)

    if args.ha_discovery:
        publish_discovery(
            client,
            prefix=args.ha_discovery_prefix,
            device_id=args.device_id,
            state_topic=state_topic,
            availability_topic=availability_topic,
        )

    while RUNNING:
        try:
            payload = build_payload(ina219)
            client.publish(state_topic, json.dumps(payload), qos=1, retain=True)
        except Exception as exc:
            print(f"Read/publish error: {exc}", file=sys.stderr)
        time.sleep(max(1, args.poll_interval))

    client.publish(availability_topic, payload="offline", qos=1, retain=True)
    client.loop_stop()
    client.disconnect()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
