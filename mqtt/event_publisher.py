import json
import time

import paho.mqtt.client as mqtt

from config import BRANCH_ID
from mqtt.shared_client import SharedMqttClient


class EventPublisher:
    """Publishes detection events (state transitions, open/close, alerts) over
    vault/{thing}/{vault_number}/{shelf_number}/data — the same per-device,
    per-shelf topic shape PickupVerifier's requests use, not a flat vault/events
    topic. The company AWS IoT device policy only authorizes iot:Publish on
    vault/${ThingName}/*/*/data (and the RFID scan topic); a flat vault/events
    topic isn't covered by it. Publishing there over AWS IoT Core gets the
    connection killed by the broker as a policy violation, and since it's a
    QoS-1 message that never gets PUBACK'd, the MQTT library keeps redelivering
    it on every reconnect -- a permanent disconnect/reconnect loop that (since
    this shares one connection with PickupVerifier, see shared_client.py) would
    take the whole Pi offline, not just event publishing. Confirmed against the
    real company AWS IoT Core endpoint before this fix.

    Events without a real shelf_number (e.g. OPEN_CLOSE_DETECTION, which is
    whole-vault-door, not per-shelf) fall back to shelf_number 0 for the topic
    only -- the payload still carries the real (possibly None) shelf_number.

    aurus-guard's weight-scale handler already reads this same topic shape and
    currently only special-cases {"event": "TRAY_PICKED", ...} messages on it;
    everything this class publishes uses "event_type" instead specifically to
    avoid colliding with that dispatch. The backend doesn't yet have a consumer
    for these event_type messages -- until it does, it will fall through into
    weight-processing logic for them, which is expected and tracked separately,
    not something this class can fix from the edge side.

    Pi only ever does this one MQTT publish — no HTTPS, no notification logic, no
    secrets beyond the MQTT broker credentials it already needs. The backend is
    what subscribes, stores it, and decides what to notify (Google Chat today,
    PagerDuty or anything else later) — keeping that decision, and those
    secrets, off every device in the field.

    Shares its MQTT connection with PickupVerifier (see mqtt/shared_client.py) —
    AWS IoT Core's device policy only allows one client_id per device, so two
    independent connections fight over it.
    """

    def __init__(self, shared: SharedMqttClient):
        self.shared = shared
        self.enabled = shared.enabled

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

        topic = f"vault/{self.shared.thing}/{vault_number}/{shelf_number if shelf_number is not None else 0}/data"
        try:
            result = self.shared.client.publish(topic, json.dumps(payload), qos=1)
            if result.rc != mqtt.MQTT_ERR_SUCCESS:
                print(f"EventPublisher: publish failed rc={result.rc} event={event_type}")
        except Exception as e:
            print(f"EventPublisher: publish error: {e} event={event_type}")
