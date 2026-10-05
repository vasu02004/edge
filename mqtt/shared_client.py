from urllib.parse import urlparse

import paho.mqtt.client as mqtt

from config import BRANCH_ID, MQTT_BROKER_URL, MQTT_CERT_PATH, MQTT_PASSWORD, MQTT_USERNAME
from mqtt.tls_auth import configure_auth


def thing_id() -> str:
    """'pi-{BRANCH_ID}' over AWS IoT Core (cert-based, matching the device's
    registered Thing Name) or plain '{BRANCH_ID}' over a non-AWS broker like
    HiveMQ -- aurus-guard's own publishCommand() uses this same split
    (WeightService.ts), so topics have to match it on both ends."""
    return f"pi-{BRANCH_ID}" if MQTT_CERT_PATH else BRANCH_ID


class SharedMqttClient:
    """One MQTT connection for the whole Pi process, shared by EventPublisher and
    PickupVerifier.

    AWS IoT Core's device policy scopes iot:Connect to
    client/${iot:Connection.Thing.ThingName} with no wildcard, so every connection
    from this device has to use the exact same client_id (the cert's registered
    Thing Name) -- two separate connections, each picking their own client_id,
    get silently rejected/kicked off by AWS IoT Core (no CONNACK, just repeated
    "Unspecified error" disconnects, confirmed against the real company AWS IoT
    Core endpoint). One shared client with the one client_id the policy actually
    allows is the only thing that works without an AWS-side policy change; it
    also means one live connection on hardware already tight on CPU instead of
    two.
    """

    def __init__(
        self,
        broker_url: str = MQTT_BROKER_URL,
        username: str = MQTT_USERNAME,
        password: str = MQTT_PASSWORD,
    ):
        self.thing = thing_id()
        self.enabled = bool(broker_url)
        self.client = None
        self._subscriptions = []
        if not self.enabled:
            print("SharedMqttClient: MQTT_BROKER_URL not set, MQTT disabled")
            return

        parsed = urlparse(broker_url)
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=self.thing)
        configure_auth(self.client, broker_url, username, password)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.reconnect_delay_set(min_delay=1, max_delay=30)

        try:
            self.client.connect_async(parsed.hostname, parsed.port or 8883, keepalive=60)
            self.client.loop_start()
        except Exception as e:
            print(f"SharedMqttClient: connection setup failed: {e}")
            self.enabled = False
            self.client = None

    def subscribe(self, topic: str):
        """Registers a topic to (re)subscribe to on every successful connect,
        including reconnects -- brokers, AWS IoT Core included, drop
        subscriptions across a disconnect."""
        self._subscriptions.append(topic)
        if self.client is not None:
            self.client.subscribe(topic)

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        if reason_code == 0:
            print(f"SharedMqttClient: connected to MQTT broker as {self.thing}")
            for topic in self._subscriptions:
                client.subscribe(topic)
        else:
            print(f"SharedMqttClient: connect failed, reason_code={reason_code}")

    def _on_disconnect(self, client, userdata, flags, reason_code, properties=None):
        print(f"SharedMqttClient: disconnected from MQTT broker (reason_code={reason_code})")

    def close(self):
        if self.client is not None:
            self.client.loop_stop()
            self.client.disconnect()
