import json
import threading
import uuid
from urllib.parse import urlparse

import paho.mqtt.client as mqtt

from config import BRANCH_ID, MQTT_BROKER_URL, MQTT_PASSWORD, MQTT_USERNAME
from mqtt.tls_auth import configure_auth


class PickupVerificationTimeout(Exception):
    pass


class PickupVerifier:
    """Verifies a tray pickup against aurus-guard's active assignment over MQTT
    request/response, mirroring the existing weight-scale bridge's cmd/data pattern
    (aurusguard-pi/bridge.js + aurus-guard's drawer.service.ts) rather than a REST
    call — the Pi has no clean way to obtain a valid JWT for the REST API, and
    aurus-guard already has a working MQTT connection to extend instead.

    Publishes {"event": "TRAY_PICKED", "tray_label", "reqId"} to
    vault/pi-{BRANCH_ID}/{vault_number}/{shelf_number}/data (the tray's own home
    shelf, from the registry) and waits for a reply on .../cmd carrying the same
    reqId: {"action": "PICKUP_VERIFICATION_RESULT", "reqId", "active": bool,
    "vault_number", "shelf_number"} — the active *location*, not a tray_label,
    since aurus-guard has no concept of ArUco-based tray identity. Mapping that
    location back to a tray_label (via registry.label_for_location) is the
    caller's job, same as the old REST-based get_expected_tray_label did.
    """

    def __init__(
        self,
        broker_url: str = MQTT_BROKER_URL,
        username: str = MQTT_USERNAME,
        password: str = MQTT_PASSWORD,
        timeout: float = 3.0,
    ):
        self.enabled = bool(broker_url)
        self.timeout = timeout
        self.client = None
        self._pending = {}
        self._lock = threading.Lock()
        if not self.enabled:
            print("PickupVerifier: MQTT_BROKER_URL not set, pickup verification disabled")
            return

        parsed = urlparse(broker_url)
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"edge-pickup-verifier-{BRANCH_ID}")
        configure_auth(self.client, broker_url, username, password)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message
        self.client.reconnect_delay_set(min_delay=1, max_delay=30)

        try:
            self.client.connect_async(parsed.hostname, parsed.port or 8883, keepalive=60)
            self.client.loop_start()
        except Exception as e:
            print(f"PickupVerifier: connection setup failed: {e}")
            self.enabled = False

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        if reason_code == 0:
            cmd_topic = f"vault/pi-{BRANCH_ID}/+/+/cmd"
            client.subscribe(cmd_topic)
            print(f"PickupVerifier: connected to MQTT broker, subscribed to {cmd_topic}")
        else:
            print(f"PickupVerifier: connect failed, reason_code={reason_code}")

    def _on_disconnect(self, client, userdata, flags, reason_code, properties=None):
        print(f"PickupVerifier: disconnected from MQTT broker (reason_code={reason_code})")

    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode())
        except Exception:
            return
        req_id = payload.get("reqId")
        if req_id is None:
            return
        with self._lock:
            entry = self._pending.get(req_id)
        if entry is not None:
            entry["payload"] = payload
            entry["flag"].set()

    def get_active_location(self, tray_label: str, vault_number: int, shelf_number: int):
        """Publishes a TRAY_PICKED request on this tray's own home shelf topic and
        returns the active operation's (vault_number, shelf_number) as reported by
        aurus-guard, or None if nothing is currently active. The backend only knows
        locations, not ArUco-based tray labels, so mapping to a tray_label (via
        registry.label_for_location) happens on the caller's side, same as the old
        REST-based get_expected_tray_label did. Raises PickupVerificationTimeout if
        MQTT is unconfigured or no reply arrives within self.timeout."""
        if not self.enabled:
            raise PickupVerificationTimeout("MQTT not configured")

        req_id = str(uuid.uuid4())
        flag = threading.Event()
        with self._lock:
            self._pending[req_id] = {"flag": flag, "payload": None}

        topic = f"vault/pi-{BRANCH_ID}/{vault_number}/{shelf_number}/data"
        message = {"event": "TRAY_PICKED", "tray_label": tray_label, "reqId": req_id}
        self.client.publish(topic, json.dumps(message), qos=1)

        got_reply = flag.wait(timeout=self.timeout)
        with self._lock:
            entry = self._pending.pop(req_id, None)

        if not got_reply or entry is None or entry["payload"] is None:
            raise PickupVerificationTimeout(f"no response within {self.timeout}s (reqId={req_id})")

        response = entry["payload"]
        if not response.get("active"):
            return None
        return response.get("vault_number"), response.get("shelf_number")

    def close(self):
        if self.client is not None:
            self.client.loop_stop()
            self.client.disconnect()
