import os


def parse_camera_source(raw: str):
    raw = raw.strip()
    if raw.isdigit():
        return int(raw)
    return raw  # e.g. a DroidCam network URL like http://<phone-ip>:4747/mjpegfeed


# Single switch between camera sources: an int device index (laptop webcam,
# or DroidCam once it registers as a virtual camera device) or a URL string
# (DroidCam/IP-camera network stream). Override via env var or --cam, no code change.
CAMERA_SOURCE = parse_camera_source(os.getenv("CAMERA_SOURCE", "0"))

FRAME_WIDTH = int(os.getenv("FRAME_WIDTH", "1280"))
FRAME_HEIGHT = int(os.getenv("FRAME_HEIGHT", "720"))

# DICT_6X6_250 (36 bits/marker), not DICT_4X4_50 (16 bits/marker): the small
# 4x4 dictionary has few enough bits, and a lenient enough error-correction
# margin, that random real-world clutter (keyboards, screen bezels, printed
# text) can occasionally decode into a valid-looking code. The larger 6x6
# codespace makes that far less likely.
ARUCO_DICTIONARY = os.getenv("ARUCO_DICTIONARY", "DICT_6X6_250")

BRANCH_ID = os.getenv("BRANCH_ID", "branch_001")
TRAY_REGISTRY_PATH = os.getenv("TRAY_REGISTRY_PATH", f"registry/{BRANCH_ID}_trays.json")
ZONE_CONFIG_PATH = os.getenv("ZONE_CONFIG_PATH", f"zone_config/{BRANCH_ID}_zones.json")

AURUS_GUARD_BASE_URL = os.getenv("AURUS_GUARD_BASE_URL", "http://localhost:3000/api/v1")
# Dev-only auth bypass: RolesGuard accepts this header directly instead of a
# real JWT (it's what the production Kong gateway would normally inject).
# Replace with real token-based auth once this moves past local testing.
AURUS_GUARD_DEV_USER_PROFILE = os.getenv(
    "AURUS_GUARD_DEV_USER_PROFILE", '{"id":"edge-tracker","roles":[{"name":"agent"}]}'
)
