import json
import re
import threading
import time
from datetime import datetime, timezone

import paho.mqtt.client as mqtt
import serial

from config import BAUDRATE, BRANCH_ID, MQTT_BROKER_URL, MQTT_PASSWORD, MQTT_USERNAME, SERIAL_PORT_PATH
from logging_utils import log
from mqtt.client import build_client

# A frame not seen in this long counts the scale as offline even if the serial
# port itself never raised an error (e.g. the indicator hangs but the
# USB-serial adapter stays enumerated).
SCALE_STALE_AFTER_SECONDS = 5

# The Aczet CY 3102 streams continuously with NO \r/\n between readings -- each
# frame is a mode letter (observed: 'N' for its Net mode), padding spaces, the
# weight value, then a literal ESC + "enter." terminator, then a status byte
# ('!' while the reading is still settling, ' ' once stable). E.g., captured
# via `od -An -tx1z /dev/ttyUSB0`:
#   4e 20...20 33 37 33 2e 30 35 1b 65 6e 74 65 72 2e 21
#   N  <spaces>  3  7  3  .  0  5 ESC  e  n  t  e  r  .  !
# There is no separate gross/tare channel over serial -- this is a single
# continuously-updating reading, so gross_weight mirrors net_weight below and
# tare_weight always stays 0.0 (the balance's own physical tare/zero offset
# isn't visible to us, only its already-tared result).
FRAME_RE = re.compile(rb"[A-Za-z]\s+([+-]?\d+(?:\.\d+)?)\x1benter\.[ !]")
MAX_BUFFER = 256

# =====================================
# LOGGING
# =====================================


def iso_timestamp():
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


log("INFO", "Scale Bridge Starting")
log("INFO", f"Branch ID: {BRANCH_ID}")
log("INFO", f"Serial Port: {SERIAL_PORT_PATH}")
log("INFO", f"MQTT Broker: {MQTT_BROKER_URL}")

# =====================================
# STATE
# =====================================

state_lock = threading.Lock()

gross_weight = 0.0
net_weight = 0.0
tare_weight = 0.0
is_scale_connected = False
last_frame_time = 0.0


def read_weights():
    with state_lock:
        return gross_weight, net_weight, tare_weight


def scale_status():
    with state_lock:
        connected, last_seen = is_scale_connected, last_frame_time
    if not connected:
        return "SCALE_OFFLINE"
    if time.monotonic() - last_seen > SCALE_STALE_AFTER_SECONDS:
        return "SCALE_OFFLINE"
    return "SUCCESS"


# =====================================
# SERIAL PORT SETUP
# =====================================

port = None
try:
    port = serial.Serial(port=SERIAL_PORT_PATH, baudrate=BAUDRATE, timeout=1)
except serial.SerialException as err:
    is_scale_connected = False
    log("ERROR", f"Serial Error: {err}")
else:
    is_scale_connected = True
    log("INFO", "Serial Port Connected")


def serial_reader():
    global gross_weight, net_weight, is_scale_connected, last_frame_time

    buffer = b""

    while True:
        try:
            chunk = port.read(64)
        except serial.SerialException as err:
            with state_lock:
                is_scale_connected = False
            log("ERROR", f"Serial Error: {err}")
            break

        if not chunk:
            # Just a read timeout (see SCALE_STALE_AFTER_SECONDS) with no data — loop
            # so a scale that's gone quiet without a serial-level error still gets
            # noticed as stale via scale_status(), instead of blocking here forever.
            continue

        with state_lock:
            is_scale_connected = True
            last_frame_time = time.monotonic()

        buffer += chunk

        try:
            match_end = 0
            for match in FRAME_RE.finditer(buffer):
                try:
                    weight = float(match.group(1))
                except ValueError:
                    log("WARN", f"Unparseable weight value: {match.group(1)!r}")
                else:
                    with state_lock:
                        net_weight = weight
                        gross_weight = weight
                match_end = match.end()

            if match_end:
                buffer = buffer[match_end:]
            elif len(buffer) > MAX_BUFFER:
                # No frame boundary found in a while -- drop stale bytes instead of
                # growing unbounded (e.g. a garbled or desynced stream).
                buffer = buffer[-MAX_BUFFER:]
        except Exception as err:
            log("ERROR", f"Scale Parse Error: {err}")

    with state_lock:
        is_scale_connected = False
    log("WARN", "Serial Port Closed")


if port is not None:
    threading.Thread(target=serial_reader, daemon=True).start()

# =====================================
# MQTT SETUP
# =====================================

log("INFO", f"Connecting to MQTT Broker: {MQTT_BROKER_URL}")

client, mqtt_host, mqtt_port = build_client(MQTT_BROKER_URL, MQTT_USERNAME, MQTT_PASSWORD, default_port=1883)
client.reconnect_delay_set(min_delay=5, max_delay=5)


def on_connect(client, userdata, flags, reason_code, properties=None):
    if reason_code != 0:
        log("ERROR", f"MQTT Error: connect failed, reason_code={reason_code}")
        return

    log("INFO", "Connected to MQTT Broker")

    cmd_topic = f"vault/{BRANCH_ID}/+/+/cmd"

    result, _ = client.subscribe(cmd_topic)
    if result != mqtt.MQTT_ERR_SUCCESS:
        log("ERROR", f"Subscribe Error: rc={result}")
    else:
        log("INFO", f"Subscribed to: {cmd_topic}")


def on_disconnect(client, userdata, flags, reason_code, properties=None):
    if reason_code != 0:
        log("WARN", "Reconnecting to MQTT Broker...")
    else:
        log("WARN", "MQTT Client Offline")


def on_log(client, userdata, level, buf):
    if level == mqtt.MQTT_LOG_ERR:
        log("ERROR", f"MQTT Error: {buf}")


# =====================================
# MQTT MESSAGE HANDLER
# =====================================


def on_message(client, userdata, message):
    try:
        payload = json.loads(message.payload.decode())

        parts = message.topic.split("/")

        if len(parts) < 5:
            log("WARN", f"Invalid topic format: {message.topic}")
            return

        branch_id = parts[1]
        vault_number = parts[2]
        shelf_number = parts[3]

        if branch_id != BRANCH_ID:
            log("WARN", f"Ignoring message from branch {branch_id}")
            return

        response_topic = f"vault/{branch_id}/{vault_number}/{shelf_number}/data"

        # ---------- READ ----------
        if payload.get("action") == "READ":
            gross, net, tare = read_weights()
            status = scale_status()

            log(
                "INFO",
                f"Weight Request | ReqID={payload.get('reqId')} | Gross={gross} | "
                f"Net={net} | Tare={tare} | Status={status}",
            )

            response = {
                "reqId": payload.get("reqId"),
                "weight": net,
                "grossWeight": gross,
                "tareWeight": tare,
                "status": status,
                "timestamp": iso_timestamp(),
            }

            if payload.get("packet_id"):
                response["packet_id"] = payload["packet_id"]

            if payload.get("context"):
                response["context"] = payload["context"]

            result = client.publish(response_topic, json.dumps(response), qos=1)
            if result.rc != mqtt.MQTT_ERR_SUCCESS:
                log("ERROR", f"Publish Error: rc={result.rc}")
            else:
                log("INFO", f"Response Published → {response_topic}")

            return

        # ---------- TARE ----------
        if payload.get("action") == "TARE":
            # NOTE: writing b"T" to trigger a remote tare on the Aczet CY 3102 is
            # UNVERIFIED -- the captured protocol (see FRAME_RE above) is a
            # continuous read-only stream with no documented command set, so
            # there's no confirmed evidence this byte does anything. Watch the
            # live reading after a TARE request to see if it actually zeros; if
            # not, taring may only be possible via the balance's own front-panel
            # button.
            try:
                port.write(b"T")
            except (serial.SerialException, AttributeError) as err:
                log("ERROR", f"Serial Write Error (TARE): {err}")
            else:
                log("INFO", f"Tare Command Sent to Scale (unverified command) | ReqID={payload.get('reqId')}")

            gross, net, tare = read_weights()

            response = {
                "reqId": payload.get("reqId"),
                "action": "TARE",
                "grossWeight": gross,
                "tareWeight": tare,
                "weight": net,
                "status": scale_status(),
                "note": "Tare command sent to scale; reflects on next frame if supported by indicator firmware.",
                "timestamp": iso_timestamp(),
            }

            if payload.get("packet_id"):
                response["packet_id"] = payload["packet_id"]

            if payload.get("context"):
                response["context"] = payload["context"]

            result = client.publish(response_topic, json.dumps(response), qos=1)
            if result.rc != mqtt.MQTT_ERR_SUCCESS:
                log("ERROR", f"Publish Error: rc={result.rc}")
            else:
                log("INFO", f"Tare Response Published → {response_topic}")

            return
    except Exception as err:
        log("ERROR", f"Message Processing Error: {err}")


client.on_connect = on_connect
client.on_disconnect = on_disconnect
client.on_message = on_message
client.on_log = on_log

# =====================================
# HEALTH LOG EVERY 5 MINUTES
# =====================================


def health_log():
    gross, net, tare = read_weights()
    log(
        "HEALTH",
        f"Gross={gross} | Net={net} | Tare={tare} | "
        f"Scale={'CONNECTED' if scale_status() == 'SUCCESS' else 'DISCONNECTED'}",
    )
    threading.Timer(300, health_log).start()


if __name__ == "__main__":
    threading.Timer(300, health_log).start()

    client.connect_async(mqtt_host, mqtt_port, keepalive=60)
    client.loop_forever(retry_first_connection=True)
