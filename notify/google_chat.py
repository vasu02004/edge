import threading

import requests

from config import GOOGLE_CHAT_WEBHOOK_URL


class GoogleChatNotifier:
    """Posts a plain-text message to a Google Chat Space via an Incoming Webhook.
    The actual HTTP call runs on its own thread — notify() must never block the
    caller, since it's invoked from the main detection loop and a webhook round-trip
    (a few hundred ms typically, up to the timeout worst-case) would otherwise stall
    frame capture every time an event fires. Failures never raise either way.
    """

    def __init__(self, webhook_url: str = GOOGLE_CHAT_WEBHOOK_URL, timeout: float = 5.0):
        self.webhook_url = webhook_url
        self.enabled = bool(webhook_url)
        self.timeout = timeout
        if not self.enabled:
            print("GoogleChatNotifier: GOOGLE_CHAT_WEBHOOK_URL not set, notifications disabled")

    def notify(self, text: str):
        if not self.enabled:
            return
        threading.Thread(target=self._send, args=(text,), daemon=True).start()

    def _send(self, text: str):
        try:
            response = requests.post(self.webhook_url, json={"text": text}, timeout=self.timeout)
            if response.status_code >= 300:
                print(
                    f"GoogleChatNotifier: notify failed status={response.status_code} "
                    f"body={response.text[:200]}"
                )
        except Exception as e:
            print(f"GoogleChatNotifier: notify error: {e}")
