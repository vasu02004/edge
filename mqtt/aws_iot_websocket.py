"""Signs an AWS IoT Core WebSocket MQTT connection URL using IAM credentials
(SigV4), the same auth method aurus-guard's own backend already uses (see
aurus-guard/src/common/mqtt/aws-iot-websocket.ts) — faithfully ported from that
file rather than using a different signer, so both sides sign identically.
Avoids needing an X.509 device certificate/Thing Name at all; authenticates as
whatever IAM principal boto3 resolves (env vars, ~/.aws/credentials, or an
attached role) instead.
"""

import hashlib
import hmac
from datetime import datetime, timezone
from urllib.parse import quote

import boto3


def _sign(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _sha256_hex(msg: str) -> str:
    return hashlib.sha256(msg.encode("utf-8")).hexdigest()


def sign_aws_iot_websocket_path(host: str, region: str) -> str:
    """Returns the path+query string (e.g. "/mqtt?X-Amz-...") to use with an
    AWS IoT Core WebSocket connection — pass this to paho-mqtt's
    ws_set_options(path=...) on a transport="websockets" client."""
    credentials = boto3.Session().get_credentials()
    if credentials is None:
        raise RuntimeError("No AWS credentials resolved (checked env vars, ~/.aws/credentials, IAM role)")
    frozen = credentials.get_frozen_credentials()

    service = "iotdevicegateway"
    algorithm = "AWS4-HMAC-SHA256"

    amz_date = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    date_stamp = amz_date[:8]
    credential_scope = f"{date_stamp}/{region}/{service}/aws4_request"

    query_params = [
        ("X-Amz-Algorithm", algorithm),
        ("X-Amz-Credential", f"{frozen.access_key}/{credential_scope}"),
        ("X-Amz-Date", amz_date),
        ("X-Amz-SignedHeaders", "host"),
    ]
    canonical_querystring = "&".join(f"{quote(k, safe='')}={quote(v, safe='')}" for k, v in query_params)

    canonical_headers = f"host:{host}\n"
    signed_headers = "host"
    payload_hash = _sha256_hex("")
    canonical_request = "\n".join(
        ["GET", "/mqtt", canonical_querystring, canonical_headers, signed_headers, payload_hash]
    )

    string_to_sign = "\n".join([algorithm, amz_date, credential_scope, _sha256_hex(canonical_request)])

    k_date = _sign(f"AWS4{frozen.secret_key}".encode("utf-8"), date_stamp)
    k_region = _sign(k_date, region)
    k_service = _sign(k_region, service)
    k_signing = _sign(k_service, "aws4_request")
    signature = hmac.new(k_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

    path = f"/mqtt?{canonical_querystring}&X-Amz-Signature={signature}"
    if frozen.token:
        path += f"&X-Amz-Security-Token={quote(frozen.token, safe='')}"
    return path
