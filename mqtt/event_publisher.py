import json
import time
from urllib.parse import urlparse

import paho.mqtt.client as mqtt

from config import BRANCH_ID, MQTT_BROKER_URL, MQTT_EVENTS_TOPIC, MQTT_PASSWORD, MQTT_USERNAME
from notify.google_chat import GoogleChatNotifier


class EventPublisher:
    """Publishes detection events (state transitions, open/close, alerts) to a flat
    MQTT topic — vault/events — with full identity (branch/vault/shelf) carried in
    the JSON payload rather than the topic path, since unlike aurusguard-pi's
    bridge.js (an addressed request/response), we're pushing telemetry with no
    incoming request to route against. Also fans each event out to Google Chat
    (via GoogleChatNotifier) so a human reviewer gets notified — during this
    validation phase that's every event, not just alerts, since reviewers
    cross-check each one against CCTV footage.
    """

    def __init__(
        self,
        broker_url: str = MQTT_BROKER_URL,
        username: str = MQTT_USERNAME,
        password: str = MQTT_PASSWORD,
        topic: str = MQTT_EVENTS_TOPIC,
        chat_notifier: GoogleChatNotifier = None,
    ):
        self.topic = topic
        self.enabled = bool(broker_url)
        self.client = None
        self.chat_notifier = chat_notifier if chat_notifier is not None else GoogleChatNotifier()
        if not self.enabled:
            print("EventPublisher: MQTT_BROKER_URL not set, MQTT publishing disabled")
            return

        parsed = urlparse(broker_url)
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        if username:
            self.client.username_pw_set(username, password)
        if parsed.scheme == "mqtts":
            self.client.tls_set()
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.reconnect_delay_set(min_delay=1, max_delay=30)

        try:
            self.client.connect_async(parsed.hostname, parsed.port or 8883, keepalive=60)
            self.client.loop_start()
        except Exception as e:
            print(f"EventPublisher: connection setup failed: {e}")
            self.enabled = False

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        if reason_code == 0:
            print("EventPublisher: connected to MQTT broker")
        else:
            print(f"EventPublisher: connect failed, reason_code={reason_code}")

    def _on_disconnect(self, client, userdata, flags, reason_code, properties=None):
        print(f"EventPublisher: disconnected from MQTT broker (reason_code={reason_code})")

    def publish(self, event_type: str, tray_label=None, vault_number=None, shelf_number=None, **extra):
        payload = {
            "event_type": event_type,
            "branch_id": BRANCH_ID,
            "vault_number": vault_number,
            "shelf_number": shelf_number,
            "tray_label": tray_label,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z",
        }
        payload.update(extra)

        if self.enabled:
            try:
                result = self.client.publish(self.topic, json.dumps(payload), qos=1)
                if result.rc != mqtt.MQTT_ERR_SUCCESS:
                    print(f"EventPublisher: publish failed rc={result.rc} event={event_type}")
            except Exception as e:
                print(f"EventPublisher: publish error: {e} event={event_type}")

        self.chat_notifier.notify(self._format_message(payload))

    @staticmethod
    def _format_message(payload: dict) -> str:
        # vault_number is constant across this branch's messages (not worth repeating),
        # and shelf_number is redundant once tray_label is shown — both still travel in
        # full in the MQTT JSON payload, this only trims the human-readable Chat text.
        location_bits = []
        if payload.get("tray_label"):
            location_bits.append(f"tray={payload['tray_label']}")
        elif payload.get("shelf_number") is not None:
            location_bits.append(f"shelf={payload['shelf_number']}")
        location = " ".join(location_bits)

        skip = {"event_type", "branch_id", "vault_number", "shelf_number", "tray_label", "timestamp"}

        def _fmt(key, value):
            if key == "confidence" and isinstance(value, (int, float)):
                return f"{value:.0%}"
            return str(value)

        detail_bits = " ".join(f"{k}={_fmt(k, v)}" for k, v in payload.items() if k not in skip)

        parts = [f"[{payload['event_type']}]", payload["branch_id"], location, detail_bits, f"@ {payload['timestamp']}"]
        return " ".join(p for p in parts if p)

    def close(self):
        if self.client is not None:
            self.client.loop_stop()
            self.client.disconnect()
