import argparse
import os
import time

import cv2

try:
    _CLK_TCK = os.sysconf("SC_CLK_TCK")
except (AttributeError, ValueError, OSError):
    _CLK_TCK = None


def proc_stats():
    """(cpu_seconds_total, rss_mb) for this process. Linux only (/proc); returns
    (None, None) elsewhere (e.g. macOS outside a Linux container)."""
    if _CLK_TCK is None:
        return None, None
    try:
        with open("/proc/self/stat") as f:
            parts = f.read().split()
        utime, stime = int(parts[13]), int(parts[14])
        cpu_seconds = (utime + stime) / _CLK_TCK
        rss_kb = None
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    rss_kb = int(line.split()[1])
                    break
        return cpu_seconds, (rss_kb / 1024 if rss_kb is not None else None)
    except (OSError, IndexError, ValueError):
        return None, None

from camera.capture import open_camera
from config import (
    CAMERA_SOURCE,
    FRAME_HEIGHT,
    FRAME_WIDTH,
    OPEN_CLOSE_IMG_SIZE,
    OPEN_CLOSE_MODEL_PATH,
    parse_camera_source,
)
from aurus_guard.client import AurusGuardClient
from detection.aruco_detector import ArucoDetector
from detection.open_close_detector import OpenCloseDetector
from detection.zones import ZoneChecker
from registry.tray_registry import TrayRegistry
from state_machine.rules import check_wrong_tray
from state_machine.tray_state import TRAY_PICKED, TrayStateMachine
from streaming.mjpeg_server import MJPEGStreamer

RED = "\033[91m"
RESET = "\033[0m"

ZONE_DRAW_COLORS = {
    "vault_zone": (0, 165, 255),
    "table_zone": (255, 0, 255),
    "boundary": (255, 255, 0),
}

OPEN_CLOSE_LABEL_COLORS = {"open": (0, 200, 0), "closed": (0, 0, 220)}

#will be changed after the camera is placed in a branch with its height and area coverage
ARUCO_FRAME_INTERVAL = 3
# Heavier YOLO open/close model runs on a slower cadence than the cheap ArUco check.
YOLO_FRAME_INTERVAL = 6
CAPTURE_LOOP_DELAY = 0.01

# Motion gating: skip a detection cycle entirely if the scene hasn't changed since
# the last one — trays sit still between pick/place events, so most cycles on a
# fixed vault camera are otherwise wasted work.
MOTION_GATING_ENABLED = False
MOTION_CHECK_SIZE = (160, 90)
MOTION_THRESHOLD = 2.0
MOTION_FORCE_RECHECK_EVERY = 30

STATS_INTERVAL = 5.0


def motion_score(prev_small, frame):
    small = cv2.cvtColor(cv2.resize(frame, MOTION_CHECK_SIZE), cv2.COLOR_BGR2GRAY)
    if prev_small is None:
        return None, small
    return float(cv2.absdiff(small, prev_small).mean()), small


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--cam",
        default=None,
        help="Camera source: device index (e.g. 1) or stream URL (e.g. http://<ip>:4747/mjpegfeed). "
        "Overrides the CAMERA_SOURCE env var if given.",
    )
    parser.add_argument(
        "--display",
        action="store_true",
        help="Show the annotated feed in a local cv2 window (requires a display/X server). "
        "Default is headless: serve the feed over HTTP instead.",
    )
    parser.add_argument(
        "--stream",
        action="store_true",
        help="Serve the annotated feed over HTTP MJPEG. Default is logs-only, no video output "
        "(skips annotation/encoding entirely to save CPU). Ignored with --display.",
    )
    parser.add_argument(
        "--stream-port",
        type=int,
        default=8080,
        help="Port for the HTTP MJPEG stream (default 8080). Only used with --stream.",
    )
    return parser.parse_args()


def annotate(frame, registered_detections, zones, open_close_detections=()):
    annotated = frame.copy()

    for zone_name, color in ZONE_DRAW_COLORS.items():
        polygon = zones.polygon(zone_name)
        if polygon is not None:
            thickness = 2 if zone_name == "boundary" else 1
            cv2.polylines(annotated, [polygon], True, color, thickness)

    for oc in open_close_detections:
        x1, y1, x2, y2 = oc["box"]
        color = OPEN_CLOSE_LABEL_COLORS.get(oc["label"], (255, 255, 255))
        cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)
        cv2.putText(
            annotated,
            f"{oc['label']} ({oc['confidence']:.0%})",
            (x1, max(20, y1 - 8)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            color,
            2,
        )

    for d in registered_detections:
        pts = d["corners"].astype(int)
        cv2.polylines(annotated, [pts], True, (0, 255, 0), 2)
        cx, cy = d["centroid"]
        cv2.circle(annotated, (int(cx), int(cy)), 4, (0, 0, 255), -1)

        if d.get("within_boundary", True):
            label_text = f"{d['tray_label']} (id={d['id']}) [{d['zone']}] {d['state']}"
            label_color = (0, 0, 139)
        else:
            label_text = f"{d['tray_label']} (id={d['id']}) OUT_OF_BOUNDARY"
            label_color = (0, 0, 255)

        cv2.putText(
            annotated,
            label_text,
            (int(cx) + 8, int(cy)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.4,
            label_color,
            2,
        )
    return annotated


def main():
    args = parse_args()
    source = parse_camera_source(args.cam) if args.cam is not None else CAMERA_SOURCE
    print(f"Opening camera source: {source!r}")
    cap = open_camera(source)
    detector = ArucoDetector()
    open_close_detector = OpenCloseDetector()
    print(f"Loaded open/close model, device={open_close_detector.device}")
    registry = TrayRegistry()
    print(f"Loaded tray registry for {registry.branch_id}: {registry.registered_labels()}")
    zones = ZoneChecker()
    print(f"Loaded zone config for {zones.branch_id}")
    tray_state_machine = TrayStateMachine()
    aurus_guard_client = AurusGuardClient()

    streamer = None
    if args.display:
        window_name = "Vault Tracker - Step 2 (press q to quit)"
        cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
        cv2.moveWindow(window_name, 100, 100)
        cv2.resizeWindow(window_name, 960, 540)
        print("Camera opened. Press 'q' in the video window (or Ctrl+C here) to stop.")
        print("If you don't see the window, check Cmd+Tab / other desktops — it opens at (100, 100).")
    elif args.stream:
        streamer = MJPEGStreamer(port=args.stream_port)
        streamer.start()
        print("Camera opened. Ctrl+C here to stop.")
    else:
        print("Camera opened, logs-only (no --display/--stream). Ctrl+C here to stop.")

    print(
        f"CONFIG frame={FRAME_WIDTH}x{FRAME_HEIGHT} aruco_interval={ARUCO_FRAME_INTERVAL} "
        f"yolo_interval={YOLO_FRAME_INTERVAL} yolo_imgsz={OPEN_CLOSE_IMG_SIZE} "
        f"yolo_model={OPEN_CLOSE_MODEL_PATH} motion_gating={MOTION_GATING_ENABLED} "
        f"motion_threshold={MOTION_THRESHOLD} capture_delay={CAPTURE_LOOP_DELAY}"
    )

    try:
        first_frame = True
        frame_count = 0
        registered = []
        open_close_detections = []
        last_logged_zone = {}
        last_within_boundary = {}
        last_open_close_label = None
        motion_ref_frame = None
        checks_since_full = 0

        stats_window_start = time.monotonic()
        stats_cpu_start, _ = proc_stats()
        frames_captured = 0
        grab_fails = 0
        motion_skips = 0
        aruco_times = []
        yolo_times = []

        while True:
            ok, frame = cap.read()
            if not ok:
                print("Frame grab failed, retrying...")
                grab_fails += 1
                time.sleep(0.1)
                continue

            frame = cv2.resize(frame, (FRAME_WIDTH, FRAME_HEIGHT))
            frame_count += 1
            frames_captured += 1
            if frame_count % ARUCO_FRAME_INTERVAL == 0:
                unchanged = False
                if MOTION_GATING_ENABLED:
                    score, motion_ref_frame = motion_score(motion_ref_frame, frame)
                    unchanged = (
                        score is not None
                        and score < MOTION_THRESHOLD
                        and checks_since_full < MOTION_FORCE_RECHECK_EVERY
                    )
                if unchanged:
                    checks_since_full += 1
                    motion_skips += 1
                else:
                    checks_since_full = 0
                    t0 = time.perf_counter()
                    detections = detector.detect(frame)
                    aruco_ms = (time.perf_counter() - t0) * 1000
                    print(f"[{time.strftime('%H:%M:%S')}] LATENCY aruco_ms={aruco_ms:.1f}")
                    aruco_times.append(aruco_ms)
                    registered = []
                    for d in detections:
                        label = registry.label_for(d["id"])
                        if label is None:
                            continue
                        d["tray_label"] = label
                        zone = zones.classify(d["centroid"])
                        d["zone"] = zone
                        registered.append(d)

                        if last_logged_zone.get(label) != zone:
                            cx, cy = d["centroid"]
                            print(
                                f"[{time.strftime('%H:%M:%S')}] tray={label} zone={zone} marker_id={d['id']} "
                                f"centroid=({cx:.1f}, {cy:.1f}) corners={d['corners'].tolist()}"
                            )
                            last_logged_zone[label] = zone

                        within_boundary = zones.is_within_boundary(d["centroid"])
                        d["within_boundary"] = within_boundary
                        if last_within_boundary.get(label, True) and not within_boundary:
                            print(f"[{time.strftime('%H:%M:%S')}] EVENT_CROSSED_BOUNDARY tray={label}")
                        last_within_boundary[label] = within_boundary

                    if frame_count % YOLO_FRAME_INTERVAL == 0:
                        t0 = time.perf_counter()
                        open_close_detections = open_close_detector.detect(frame)
                        yolo_ms = (time.perf_counter() - t0) * 1000
                        print(f"[{time.strftime('%H:%M:%S')}] LATENCY yolo_ms={yolo_ms:.1f}")
                        yolo_times.append(yolo_ms)
                        if open_close_detections:
                            best = max(open_close_detections, key=lambda d: d["confidence"])
                            current_open_close_label = best["label"]
                        else:
                            current_open_close_label = None
                        if current_open_close_label != last_open_close_label:
                            if current_open_close_label is not None:
                                print(
                                    f"[{time.strftime('%H:%M:%S')}] OPEN_CLOSE_DETECTION "
                                    f"label={best['label']} confidence={best['confidence']:.0%} box={best['box']}"
                                )
                            else:
                                print(f"[{time.strftime('%H:%M:%S')}] OPEN_CLOSE_DETECTION label=none")
                            last_open_close_label = current_open_close_label

                    visible_this_frame = {d["tray_label"]: d["zone"] for d in registered}

                    for label, old_state, new_state in tray_state_machine.update(visible_this_frame):
                        print(f"[{time.strftime('%H:%M:%S')}] STATE_TRANSITION tray={label} {old_state} -> {new_state}")

                        if new_state == TRAY_PICKED:
                            event, details = check_wrong_tray(label, aurus_guard_client, registry)
                            if event == "WRONG_TRAY":
                                print(
                                    f"{RED}[{time.strftime('%H:%M:%S')}] ALERT_WRONG_TRAY "
                                    f"picked={details['picked']} expected={details['expected']}{RESET}"
                                )
                            elif event == "NO_ACTIVE_ASSIGNMENT":
                                print(
                                    f"[{time.strftime('%H:%M:%S')}] NOTICE_NO_ACTIVE_ASSIGNMENT picked={details['picked']}"
                                )
                            elif event == "ASSIGNMENT_LOOKUP_FAILED":
                                print(
                                    f"[{time.strftime('%H:%M:%S')}] WARNING_ASSIGNMENT_LOOKUP_FAILED "
                                    f"picked={details['picked']} reason={details['reason']}"
                                )
                            else:
                                print(f"[{time.strftime('%H:%M:%S')}] CORRECT_TRAY_PICKED picked={details['picked']}")

                    for d in registered:
                        d["state"] = tray_state_machine.state_for(d["tray_label"])

                    if args.display:
                        annotated = annotate(frame, registered, zones, open_close_detections)
                        cv2.imshow(window_name, annotated)
                        if first_frame:
                            cv2.setWindowProperty(window_name, cv2.WND_PROP_TOPMOST, 1)
                            first_frame = False
                    elif args.stream:
                        annotated = annotate(frame, registered, zones, open_close_detections)
                        streamer.update_frame(annotated)

            if args.display and cv2.waitKey(1) & 0xFF == ord("q"):
                break

            now = time.monotonic()
            elapsed = now - stats_window_start
            if elapsed >= STATS_INTERVAL:
                fps = frames_captured / elapsed
                cpu_now, rss_mb = proc_stats()
                if cpu_now is not None and stats_cpu_start is not None:
                    cpu_pct = 100 * (cpu_now - stats_cpu_start) / elapsed
                    cpu_str = f"{cpu_pct:.1f}%"
                else:
                    cpu_str = "n/a"
                rss_str = f"{rss_mb:.1f}MB" if rss_mb is not None else "n/a"

                def _latency_str(times):
                    if not times:
                        return "calls=0"
                    return (
                        f"calls={len(times)} avg={sum(times) / len(times):.1f}ms "
                        f"min={min(times):.1f}ms max={max(times):.1f}ms"
                    )

                print(
                    f"[{time.strftime('%H:%M:%S')}] STATS window={elapsed:.1f}s fps={fps:.1f} "
                    f"cpu={cpu_str} rss={rss_str} frames={frames_captured} "
                    f"grab_fails={grab_fails} motion_skips={motion_skips} "
                    f"aruco({_latency_str(aruco_times)}) yolo({_latency_str(yolo_times)})"
                )

                stats_window_start = now
                stats_cpu_start = cpu_now
                frames_captured = 0
                grab_fails = 0
                motion_skips = 0
                aruco_times = []
                yolo_times = []

            time.sleep(CAPTURE_LOOP_DELAY)
    finally:
        cap.release()
        if args.display:
            cv2.destroyAllWindows()
        if streamer is not None:
            streamer.stop()


if __name__ == "__main__":
    main()
