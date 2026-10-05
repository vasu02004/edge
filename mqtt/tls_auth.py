from config import MQTT_CA_PATH, MQTT_CERT_PATH, MQTT_KEY_PATH


def configure_auth(client, broker_url: str, username: str, password: str):
    """Configures either X.509 device-certificate mutual TLS (AWS IoT Core's real
    device-auth scheme, used when MQTT_CERT_PATH is set) or username/password +
    plain TLS — shared by EventPublisher and PickupVerifier so both connect the
    same way. Cert-based takes precedence when both are configured.
    """
    if MQTT_CERT_PATH:
        client.tls_set(ca_certs=MQTT_CA_PATH, certfile=MQTT_CERT_PATH, keyfile=MQTT_KEY_PATH)
        return

    if username:
        client.username_pw_set(username, password)
    if broker_url.startswith("mqtts://"):
        client.tls_set()
