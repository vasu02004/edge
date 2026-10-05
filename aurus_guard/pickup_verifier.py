import json
import threading
import uuid

from mqtt.shared_client import SharedMqttClient


class PickupVerificationTimeout(Exception):
    pass


class PickupVerifier:
    """Verifies a tray pickup against aurus-guard's active assignment over MQTT
    request/response, mirroring the existing weight-scale bridge's cmd/data pattern
    (aurusguard-pi/bridge.js + aurus-guard's drawer.service.ts) rather than a REST
    call — the Pi has no clean way to obtain a valid JWT for the REST API, and
    aurus-guard already has a working MQTT connection to extend instead.

    Publishes {"event": "TRAY_PICKED", "tray_label", "reqId"} to
    vault/{thing}/{vault_number}/{shelf_number}/data (the tray's own home shelf,
    from the registry) and waits for a reply on .../cmd carrying the same reqId:
    {"action": "PICKUP_VERIFICATION_RESULT", "reqId", "active": bool,
    "vault_number", "shelf_number"} — the active *location*, not a tray_label,
    since aurus-guard has no concept of ArUco-based tray identity. Mapping that
    location back to a tray_label (via registry.label_for_location) is the
    caller's job, same as the old REST-based get_expected_tray_label did.

    Shares its MQTT connection with EventPublisher (see mqtt/shared_client.py) —
    AWS IoT Core's device policy only allows one client_id per device, so two
    independent connections fight over it.
    """

    def __init__(self, shared: SharedMqttClient, timeout: float = 3.0):
        self.shared = shared
        self.enabled = shared.enabled
        self.timeout = timeout
        self._pending = {}
        self._lock = threading.Lock()
        self._thing = shared.thing
        if not self.enabled:
            print("PickupVerifier: MQTT_BROKER_URL not set, pickup verification disabled")
            return

        cmd_topic = f"vault/{self._thing}/+/+/cmd"
        shared.client.message_callback_add(cmd_topic, self._on_message)
        shared.subscribe(cmd_topic)

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

        topic = f"vault/{self._thing}/{vault_number}/{shelf_number}/data"
        message = {"event": "TRAY_PICKED", "tray_label": tray_label, "reqId": req_id}
        self.shared.client.publish(topic, json.dumps(message), qos=1)

        got_reply = flag.wait(timeout=self.timeout)
        with self._lock:
            entry = self._pending.pop(req_id, None)

        if not got_reply or entry is None or entry["payload"] is None:
            raise PickupVerificationTimeout(f"no response within {self.timeout}s (reqId={req_id})")

        response = entry["payload"]
        if not response.get("active"):
            return None
        return response.get("vault_number"), response.get("shelf_number")
