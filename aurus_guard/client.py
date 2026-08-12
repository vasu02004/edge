from typing import Optional

import requests

from config import AURUS_GUARD_BASE_URL, AURUS_GUARD_DEV_USER_PROFILE, BRANCH_ID


class AurusGuardClient:
    """Thin client for the aurus-guard NestJS backend's drawer-state API."""

    def __init__(self, base_url: str = AURUS_GUARD_BASE_URL, branch_id: str = BRANCH_ID, timeout: float = 5.0):
        self.base_url = base_url.rstrip("/")
        self.branch_id = branch_id
        self.timeout = timeout

    def get_active_drawer(self) -> dict:
        """GET /drawer/active for this branch. Returns aurus-guard's raw
        response dict: {'status': 'NO_ACTIVE_OPERATION', ...} when nothing
        is currently assigned, or includes assetDetails.vault_number /
        assetDetails.shelf_number when a drawer operation is active."""
        response = requests.get(
            f"{self.base_url}/drawer/active",
            params={"branch_id": self.branch_id},
            headers={"x-consumer-profile": AURUS_GUARD_DEV_USER_PROFILE},
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()


def get_expected_tray_label(client: AurusGuardClient, registry) -> Optional[str]:
    """Looks up the currently-active drawer via aurus-guard and resolves it
    to our tray_label (e.g. 'S3') via the registry's vault/shelf mapping.
    Returns None if there's no active operation, or if aurus-guard reports
    a vault_number/shelf_number our registry doesn't recognize."""
    active = client.get_active_drawer()
    if active.get("status") == "NO_ACTIVE_OPERATION":
        return None

    asset_details = active.get("assetDetails") or {}
    vault_number = asset_details.get("vault_number")
    shelf_number = asset_details.get("shelf_number")
    if vault_number is None or shelf_number is None:
        return None

    return registry.label_for_location(vault_number, shelf_number)
