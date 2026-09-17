import json
import time
from urllib.parse import urlparse

import paho.mqtt.client as mqtt

from config import BRANCH_ID, MQTT_BROKER_URL, MQTT_EVENTS_TOPIC, MQTT_PASSWORD, MQTT_USERNAME
from mqtt.tls_auth import configure_auth


class EventPublisher:
    """Publishes detection events (state transitions, open/close, alerts) to a flat
    MQTT topic — vault/events — with full identity (branch/vault/shelf) carried in
    the JSON payload rather than the topic path, since unlike aurusguard-pi's
    bridge.js (an addressed request/response), we're pushing telemetry with no
    incoming request to route against.

    Pi only ever does this one MQTT publish — no HTTPS, no notification logic, no
    secrets beyond the MQTT broker credentials it already needs. The backend is
    what subscribes to vault/events, stores it, and decides what to notify (Google
    Chat today, PagerDuty or anything else later) — keeping that decision, and
    those secrets, off every device in the field. Moving it here previously meant
    every Pi needed the Chat webhook URL, and did an HTTPS call on top of MQTT for
    every single event, on hardware already tight on CPU.
    """

    def __init__(
        self,
        broker_url: str = MQTT_BROKER_URL,
        username: str = MQTT_USERNAME,
        password: str = MQTT_PASSWORD,
        topic: str = MQTT_EVENTS_TOPIC,
    ):
        self.topic = topic
        self.enabled = bool(broker_url)
        self.client = None
        if not self.enabled:
            print("EventPublisher: MQTT_BROKER_URL not set, MQTT publishing disabled")
            return

        parsed = urlparse(broker_url)
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        configure_auth(self.client, broker_url, username, password)
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
        if not self.enabled:
            return
        payload = {
            "event_type": event_type,
            "branch_id": BRANCH_ID,
            "vault_number": vault_number,
            "shelf_number": shelf_number,
            "tray_label": tray_label,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z",
        }
        payload.update(extra)

        try:
            result = self.client.publish(self.topic, json.dumps(payload), qos=1)
            if result.rc != mqtt.MQTT_ERR_SUCCESS:
                print(f"EventPublisher: publish failed rc={result.rc} event={event_type}")
        except Exception as e:
            print(f"EventPublisher: publish error: {e} event={event_type}")

    def close(self):
        if self.client is not None:
            self.client.loop_stop()
            self.client.disconnect()
