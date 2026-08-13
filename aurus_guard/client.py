from typing import Optional

import requests

from config import AURUS_GUARD_BASE_URL, AURUS_GUARD_DEV_USER_PROFILE, BRANCH_ID


class AurusGuardClient:
    def __init__(self, base_url: str = AURUS_GUARD_BASE_URL, branch_id: str = BRANCH_ID, timeout: float = 5.0):
        self.base_url = base_url.rstrip("/")
        self.branch_id = branch_id
        self.timeout = timeout

    def get_active_drawer(self) -> dict:
        response = requests.get(
            f"{self.base_url}/drawer/active",
            params={"branch_id": self.branch_id},
            headers={"x-consumer-profile": AURUS_GUARD_DEV_USER_PROFILE},
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()


def get_expected_tray_label(client: AurusGuardClient, registry) -> Optional[str]:
    active = client.get_active_drawer()
    if active.get("status") == "NO_ACTIVE_OPERATION":
        return None

    asset_details = active.get("assetDetails") or {}
    vault_number = asset_details.get("vault_number")
    shelf_number = asset_details.get("shelf_number")
    if vault_number is None or shelf_number is None:
        return None

    return registry.label_for_location(vault_number, shelf_number)
