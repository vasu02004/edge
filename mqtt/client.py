from urllib.parse import urlparse

import paho.mqtt.client as mqtt


def build_client(broker_url, username="", password="", clean_session=True, default_port=1883):
    """Construct a paho MQTT client configured for `broker_url` — username/password
    auth and TLS (mqtts:// scheme) handled the same way for every caller that talks
    to this broker, instead of each caller re-parsing the URL and re-wiring auth/TLS
    itself. Returns (client, hostname, port) since connect_async() needs those split
    out of the URL anyway.
    """
    parsed = urlparse(broker_url)
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, clean_session=clean_session)
    if username:
        client.username_pw_set(username, password)
    if parsed.scheme == "mqtts":
        client.tls_set()
    return client, parsed.hostname, parsed.port or default_port
