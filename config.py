import os

from dotenv import load_dotenv

load_dotenv()


def parse_camera_source(raw: str):
    raw = raw.strip()
    if raw.isdigit():
        return int(raw)
    return raw


CAMERA_SOURCE = parse_camera_source(os.getenv("CAMERA_SOURCE", "0"))

FRAME_WIDTH = int(os.getenv("FRAME_WIDTH", "640"))
FRAME_HEIGHT = int(os.getenv("FRAME_HEIGHT", "360"))

ARUCO_DICTIONARY = os.getenv("ARUCO_DICTIONARY", "DICT_6X6_250")

BRANCH_ID = os.getenv("BRANCH_ID", "branch_001")
TRAY_REGISTRY_PATH = os.getenv("TRAY_REGISTRY_PATH", f"registry/{BRANCH_ID}_trays.json")
ZONE_CONFIG_PATH = os.getenv("ZONE_CONFIG_PATH", f"zone_config/{BRANCH_ID}_zones.json")

AURUS_GUARD_BASE_URL = os.getenv("AURUS_GUARD_BASE_URL", "http://localhost:3000/api/v1")
AURUS_GUARD_DEV_USER_PROFILE = os.getenv(
    "AURUS_GUARD_DEV_USER_PROFILE", '{"id":"edge-tracker","roles":[{"name":"agent"}]}'
)

OPEN_CLOSE_MODEL_PATH = os.getenv("OPEN_CLOSE_MODEL_PATH", "models/yolo26n_best_ncnn_model")
OPEN_CLOSE_CONF_THRESHOLD = float(os.getenv("OPEN_CLOSE_CONF_THRESHOLD", "0.5"))
OPEN_CLOSE_IOU_THRESHOLD = float(os.getenv("OPEN_CLOSE_IOU_THRESHOLD", "0.45"))
OPEN_CLOSE_IMG_SIZE = int(os.getenv("OPEN_CLOSE_IMG_SIZE", "320"))

# Per-call aruco_ms/yolo_ms prints are too high-volume for an unattended
# multi-day soak (tens of calls/sec) — off by default; the periodic STATS
# line already reports avg/min/max for both every STATS_INTERVAL.
VERBOSE_LATENCY_LOGS = os.getenv("VERBOSE_LATENCY_LOGS", "false").lower() == "true"
STATS_LOG_PATH = os.getenv("STATS_LOG_PATH", "stats.csv")

# Motion gating: skip a detection cycle entirely if the scene hasn't changed since
# the last one — trays sit still between pick/place events, so most cycles on a
# fixed vault camera are otherwise wasted work.
MOTION_GATING_ENABLED = os.getenv("MOTION_GATING_ENABLED", "false").lower() == "true"
