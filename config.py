import datetime
import os

from dotenv import load_dotenv

load_dotenv()


def parse_camera_source(raw: str):
    raw = raw.strip()
    if raw.isdigit():
        return int(raw)
    return raw


def _parse_time_of_day(raw: str) -> datetime.time:
    hour, minute = raw.strip().split(":")
    return datetime.time(int(hour), int(minute))


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

# MQTT event publishing
# Left blank = publishing disabled (EventPublisher no-ops), so this stays optional
# until configured.
MQTT_BROKER_URL = os.getenv("MQTT_BROKER_URL", "")
MQTT_USERNAME = os.getenv("MQTT_USERNAME", "")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "")
MQTT_EVENTS_TOPIC = os.getenv("MQTT_EVENTS_TOPIC", "vault/events")

# Google Chat webhook for human-reviewer notifications (validation phase: every
# event notifies, not just alerts — reviewers cross-check each one against CCTV
# footage). Blank = disabled.
GOOGLE_CHAT_WEBHOOK_URL = os.getenv("GOOGLE_CHAT_WEBHOOK_URL", "")

# Recording + upload of the raw camera feed, for CCTV-style footage review
# (separate from the annotated --stream output). Only applies when CAMERA_SOURCE
# is a local device (e.g. /dev/video0) -- ignored for an HTTP camera source such
# as a phone running an IP-camera app. A single ffmpeg process reads the device
# once and fans out to both this recording and the detection pipeline, since
# /dev/video0 only allows one consumer at a time.
RECORDING_ENABLED = os.getenv("RECORDING_ENABLED", "true").lower() == "true"
RECORDINGS_DIR = os.getenv("RECORDINGS_DIR", "/home/raspberry/recordings")
DRIVE_REMOTE = os.getenv("DRIVE_REMOTE", "gdrive:")
RECORDING_WIDTH = int(os.getenv("RECORDING_WIDTH", "1920"))
RECORDING_HEIGHT = int(os.getenv("RECORDING_HEIGHT", "1080"))
RECORDING_BITRATE = os.getenv("RECORDING_BITRATE", "8M")
RECORDING_SEGMENT_SECONDS = int(os.getenv("RECORDING_SEGMENT_SECONDS", "900"))
RECORDING_MIN_UPLOAD_AGE_SECONDS = int(os.getenv("RECORDING_MIN_UPLOAD_AGE_SECONDS", "30"))
RECORDING_UPLOAD_INTERVAL_SECONDS = int(os.getenv("RECORDING_UPLOAD_INTERVAL_SECONDS", "60"))
CAMERA_AUTO_EXPOSURE = int(os.getenv("CAMERA_AUTO_EXPOSURE", "3"))
CAMERA_BRIGHTNESS = int(os.getenv("CAMERA_BRIGHTNESS", "0"))

# Active hours: with recording enabled, the whole pipeline (detection +
# recording) only runs in this window, so there's no camera/CPU cost outside
# business hours, when no trays should be moving anyway.
ACTIVE_HOURS_START = _parse_time_of_day(os.getenv("ACTIVE_HOURS_START", "08:45"))
ACTIVE_HOURS_END = _parse_time_of_day(os.getenv("ACTIVE_HOURS_END", "18:45"))
