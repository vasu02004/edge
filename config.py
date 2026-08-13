import os


def parse_camera_source(raw: str):
    raw = raw.strip()
    if raw.isdigit():
        return int(raw)
    return raw


CAMERA_SOURCE = parse_camera_source(os.getenv("CAMERA_SOURCE", "0"))

FRAME_WIDTH = int(os.getenv("FRAME_WIDTH", "1280"))
FRAME_HEIGHT = int(os.getenv("FRAME_HEIGHT", "720"))

ARUCO_DICTIONARY = os.getenv("ARUCO_DICTIONARY", "DICT_6X6_250")

BRANCH_ID = os.getenv("BRANCH_ID", "branch_001")
TRAY_REGISTRY_PATH = os.getenv("TRAY_REGISTRY_PATH", f"registry/{BRANCH_ID}_trays.json")
ZONE_CONFIG_PATH = os.getenv("ZONE_CONFIG_PATH", f"zone_config/{BRANCH_ID}_zones.json")

AURUS_GUARD_BASE_URL = os.getenv("AURUS_GUARD_BASE_URL", "http://localhost:3000/api/v1")
AURUS_GUARD_DEV_USER_PROFILE = os.getenv(
    "AURUS_GUARD_DEV_USER_PROFILE", '{"id":"edge-tracker","roles":[{"name":"agent"}]}'
)
