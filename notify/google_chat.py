import threading
import time

import requests

from config import GOOGLE_CHAT_WEBHOOK_URL


class GoogleChatNotifier:
    """Posts a plain-text message to a Google Chat Space via an Incoming Webhook.
    The actual HTTP call runs on its own thread — notify() must never block the
    caller, since it's invoked from the main detection loop and a webhook round-trip
    (a few hundred ms typically, up to the timeout worst-case) would otherwise stall
    frame capture every time an event fires. Failures never raise either way.

    A 429 response is retried with exponential backoff (2s, 4s, 8s) since Google
    Chat webhooks are rate-limited and a burst of events can otherwise drop
    notifications outright.
    """

    def __init__(
        self,
        webhook_url: str = GOOGLE_CHAT_WEBHOOK_URL,
        timeout: float = 5.0,
        max_retries: int = 3,
        backoff_base: float = 2.0,
    ):
        self.webhook_url = webhook_url
        self.enabled = bool(webhook_url)
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        if not self.enabled:
            print("GoogleChatNotifier: GOOGLE_CHAT_WEBHOOK_URL not set, notifications disabled")

    def notify(self, text: str):
        if not self.enabled:
            return
        threading.Thread(target=self._send, args=(text,), daemon=True).start()

    def _send(self, text: str):
        for attempt in range(self.max_retries + 1):
            try:
                response = requests.post(self.webhook_url, json={"text": text}, timeout=self.timeout)
            except Exception as e:
                print(f"GoogleChatNotifier: notify error: {e}")
                return

            if response.status_code != 429:
                if response.status_code >= 300:
                    print(
                        f"GoogleChatNotifier: notify failed status={response.status_code} "
                        f"body={response.text[:200]}"
                    )
                return

            if attempt == self.max_retries:
                print(
                    f"GoogleChatNotifier: notify failed status=429 "
                    f"body={response.text[:200]} (gave up after {self.max_retries} retries)"
                )
                return

            delay = self.backoff_base * (2 ** attempt)
            retry_after = response.headers.get("Retry-After")
            if retry_after is not None:
                try:
                    delay = max(delay, float(retry_after))
                except ValueError:
                    pass
            print(f"GoogleChatNotifier: rate limited (429), retrying in {delay:.1f}s")
            time.sleep(delay)
