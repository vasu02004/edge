import argparse
import csv
import datetime
import os
import subprocess
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


def system_cpu_times():
    """(idle_jiffies, total_jiffies) summed across all cores, from /proc/stat's
    aggregate 'cpu' line. Two samples at the start/end of a window give
    system-wide CPU% the same way proc_stats()'s utime/stime deltas give
    per-process CPU% — lets a soak test tell "my process is busy" apart from
    "something else on the Pi is competing for CPU."""
    try:
        with open("/proc/stat") as f:
            parts = f.readline().split()
        values = list(map(int, parts[1:]))
        idle = values[3] + (values[4] if len(values) > 4 else 0)  # idle + iowait
        return idle, sum(values)
    except (OSError, IndexError, ValueError):
        return None, None


def system_stats():
    """(mem_available_mb, mem_used_pct, cpu_temp_c, throttled_hex) for the host.
    Each is None where unavailable (e.g. not Linux, or not a Raspberry Pi for
    throttled_hex). throttled_hex != "0x0" means a Pi under-voltage/thermal-
    throttle event happened at some point since boot — a long soak test should
    check this, since throttling silently invalidates CPU/latency numbers."""
    mem_total_mb, mem_available_mb = None, None
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    mem_total_mb = int(line.split()[1]) / 1024
                elif line.startswith("MemAvailable:"):
                    mem_available_mb = int(line.split()[1]) / 1024
    except (OSError, IndexError, ValueError):
        pass
    mem_used_pct = (
        100 * (1 - mem_available_mb / mem_total_mb)
        if mem_total_mb and mem_available_mb is not None
        else None
    )

    cpu_temp_c = None
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            cpu_temp_c = int(f.read().strip()) / 1000
    except (OSError, ValueError):
        pass

    throttled_hex = None
    try:
        result = subprocess.run(
            ["vcgencmd", "get_throttled"], capture_output=True, text=True, timeout=1
        )
        if result.returncode == 0 and "=" in result.stdout:
            throttled_hex = result.stdout.strip().split("=", 1)[1]
    except (OSError, subprocess.SubprocessError):
        pass

    return mem_available_mb, mem_used_pct, cpu_temp_c, throttled_hex


from camera.capture import open_camera
from camera.ffmpeg_capture import FfmpegDualOutputCapture, UploadWorker
from config import (
    ACTIVE_HOURS_END,
    ACTIVE_HOURS_START,
    CAMERA_AUTO_EXPOSURE,
    CAMERA_BRIGHTNESS,
    CAMERA_SOURCE,
    DRIVE_REMOTE,
    FRAME_HEIGHT,
    FRAME_WIDTH,
    OPEN_CLOSE_IMG_SIZE,
    MOTION_GATING_ENABLED,
    OPEN_CLOSE_MODEL_PATH,
    RECORDING_BITRATE,
    RECORDING_ENABLED,
    RECORDING_HEIGHT,
    RECORDING_MIN_UPLOAD_AGE_SECONDS,
    RECORDING_SEGMENT_SECONDS,
    RECORDING_UPLOAD_INTERVAL_SECONDS,
    RECORDING_WIDTH,
    RECORDINGS_DIR,
    STATS_LOG_PATH,
    VERBOSE_LATENCY_LOGS,
    parse_camera_source,
)
from aurus_guard.client import AurusGuardClient
from detection.aruco_detector import ArucoDetector
from detection.open_close_detector import OpenCloseDetector
from detection.zones import ZoneChecker
from mqtt.event_publisher import EventPublisher
from registry.tray_registry import TrayRegistry
from state_machine.rules import check_wrong_tray
from state_machine.tray_state import IDLE, TRAY_ON_TABLE, TRAY_PICKED, TrayStateMachine
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

# Motion gating (MOTION_GATING_ENABLED itself is env-driven, see config.py):
# skip a detection cycle entirely if the scene hasn't changed since the last
# one — trays sit still between pick/place events, so most cycles on a fixed
# vault camera are otherwise wasted work.
MOTION_CHECK_SIZE = (160, 90)
MOTION_THRESHOLD = 2.0
MOTION_FORCE_RECHECK_EVERY = 30

STATS_INTERVAL = 5.0


def motion_score(prev_small, frame):
    small = cv2.cvtColor(cv2.resize(frame, MOTION_CHECK_SIZE), cv2.COLOR_BGR2GRAY)
    if prev_small is None:
        return None, small
    return float(cv2.absdiff(small, prev_small).mean()), small


def is_local_device(source):
    return not (isinstance(source, str) and source.startswith(("http://", "https://")))


def to_v4l2_device_path(source):
    """ffmpeg/v4l2-ctl need an actual device path (e.g. /dev/video0), but
    CAMERA_SOURCE/--cam accepts a bare index (e.g. 0) since that's what cv2
    takes directly. Only used on the recording path -- open_camera() still
    gets the raw source, since cv2 handles a bare index itself."""
    if isinstance(source, int):
        return f"/dev/video{source}"
    return source


def is_active_hours(now):
    t = now.time()
    return ACTIVE_HOURS_START <= t <= ACTIVE_HOURS_END


def next_active_window_start(now):
    """The next datetime the active-hours window opens: today if `now` is
    before it, otherwise tomorrow."""
    today_start = datetime.datetime.combine(now.date(), ACTIVE_HOURS_START)
    return today_start if now < today_start else today_start + datetime.timedelta(days=1)


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


def detection_loop(
    cap,
    streamer,
    args,
    window_name,
    detector,
    open_close_detector,
    registry,
    zones,
    tray_state_machine,
    aurus_guard_client,
    event_publisher,
    stats_csv,
    stats_log_file,
    stop_at=None,
):
    """Runs detection against `cap` until the display window is quit, wall-clock
    time passes `stop_at` (a time.monotonic() deadline; None runs forever), or
    -- only when `stop_at` is set, i.e. an active-hours recording session --
    the camera stops producing frames. Returns "quit", "deadline", or
    "cap_lost". Does not open/close `cap` or any of the objects passed in; the
    caller owns their lifecycle."""
    CONSECUTIVE_GRAB_FAIL_LIMIT = 50

    first_frame = True
    frame_count = 0
    registered = []
    open_close_detections = []
    last_logged_zone = {}
    last_within_boundary = {}
    last_open_close_label = None
    motion_ref_frame = None
    checks_since_full = 0
    consecutive_grab_fails = 0

    stats_window_start = time.monotonic()
    stats_cpu_start, _ = proc_stats()
    system_idle_start, system_total_start = system_cpu_times()
    frames_captured = 0
    grab_fails = 0
    motion_skips = 0
    aruco_times = []
    yolo_times = []

    while True:
        if stop_at is not None and time.monotonic() >= stop_at:
            return "deadline"

        ok, frame = cap.read()
        if not ok:
            print("Frame grab failed, retrying...")
            grab_fails += 1
            consecutive_grab_fails += 1
            if stop_at is not None and consecutive_grab_fails >= CONSECUTIVE_GRAB_FAIL_LIMIT:
                print("Too many consecutive grab failures, reopening camera")
                return "cap_lost"
            time.sleep(0.1)
            continue
        consecutive_grab_fails = 0

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
                if VERBOSE_LATENCY_LOGS:
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
                        event_publisher.publish(
                            "EVENT_CROSSED_BOUNDARY",
                            tray_label=label,
                            vault_number=registry.vault_number,
                            shelf_number=registry.shelf_number_for(label),
                        )
                    last_within_boundary[label] = within_boundary

                if frame_count % YOLO_FRAME_INTERVAL == 0:
                    t0 = time.perf_counter()
                    open_close_detections = open_close_detector.detect(frame)
                    yolo_ms = (time.perf_counter() - t0) * 1000
                    if VERBOSE_LATENCY_LOGS:
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
                            event_publisher.publish(
                                "OPEN_CLOSE_DETECTION",
                                vault_number=registry.vault_number,
                                label=best["label"],
                                confidence=best["confidence"],
                                box=best["box"],
                            )
                        else:
                            print(f"[{time.strftime('%H:%M:%S')}] OPEN_CLOSE_DETECTION label=none")
                            event_publisher.publish(
                                "OPEN_CLOSE_DETECTION",
                                vault_number=registry.vault_number,
                                label=None,
                            )
                        last_open_close_label = current_open_close_label

                visible_this_frame = {d["tray_label"]: d["zone"] for d in registered}

                for label, old_state, new_state in tray_state_machine.update(visible_this_frame):
                    print(f"[{time.strftime('%H:%M:%S')}] STATE_TRANSITION tray={label} {old_state} -> {new_state}")
                    event_publisher.publish(
                        "STATE_TRANSITION",
                        tray_label=label,
                        vault_number=registry.vault_number,
                        shelf_number=registry.shelf_number_for(label),
                        old_state=old_state,
                        new_state=new_state,
                    )

                    if new_state == TRAY_PICKED:
                        event, details = check_wrong_tray(label, aurus_guard_client, registry)
                        shelf_number = registry.shelf_number_for(label)
                        if event == "WRONG_TRAY":
                            print(
                                f"{RED}[{time.strftime('%H:%M:%S')}] ALERT_WRONG_TRAY "
                                f"picked={details['picked']} expected={details['expected']}{RESET}"
                            )
                            event_publisher.publish(
                                "ALERT_WRONG_TRAY",
                                tray_label=label,
                                vault_number=registry.vault_number,
                                shelf_number=shelf_number,
                                picked=details["picked"],
                                expected=details["expected"],
                            )
                        elif event == "NO_ACTIVE_ASSIGNMENT":
                            print(
                                f"[{time.strftime('%H:%M:%S')}] NOTICE_NO_ACTIVE_ASSIGNMENT picked={details['picked']}"
                            )
                            event_publisher.publish(
                                "NOTICE_NO_ACTIVE_ASSIGNMENT",
                                tray_label=label,
                                vault_number=registry.vault_number,
                                shelf_number=shelf_number,
                                picked=details["picked"],
                            )
                        elif event == "ASSIGNMENT_LOOKUP_FAILED":
                            print(
                                f"[{time.strftime('%H:%M:%S')}] WARNING_ASSIGNMENT_LOOKUP_FAILED "
                                f"picked={details['picked']} reason={details['reason']}"
                            )
                            event_publisher.publish(
                                "WARNING_ASSIGNMENT_LOOKUP_FAILED",
                                tray_label=label,
                                vault_number=registry.vault_number,
                                shelf_number=shelf_number,
                                picked=details["picked"],
                                reason=details["reason"],
                            )
                        else:
                            print(f"[{time.strftime('%H:%M:%S')}] CORRECT_TRAY_PICKED picked={details['picked']}")
                            event_publisher.publish(
                                "CORRECT_TRAY_PICKED",
                                tray_label=label,
                                vault_number=registry.vault_number,
                                shelf_number=shelf_number,
                                picked=details["picked"],
                            )

                    elif old_state == IDLE and new_state == TRAY_ON_TABLE:
                        # Tray's first-ever sighting was already on the table — we
                        # never witnessed a pickup, so there's no "picked vs
                        # expected" comparison to make. But we can still ask
                        # aurus-guard whether anything is actually authorized right
                        # now; if not, a tray sitting outside the vault with zero
                        # authorization is alert-worthy regardless of whether the
                        # camera caught the pickup moment.
                        event, details = check_wrong_tray(label, aurus_guard_client, registry)
                        shelf_number = registry.shelf_number_for(label)
                        if event in ("WRONG_TRAY", "NO_ACTIVE_ASSIGNMENT"):
                            print(
                                f"{RED}[{time.strftime('%H:%M:%S')}] ALERT_UNAUTHORIZED_TRAY_MOVEMENT "
                                f"tray={label} reason={event}{RESET}"
                            )
                            event_publisher.publish(
                                "ALERT_UNAUTHORIZED_TRAY_MOVEMENT",
                                tray_label=label,
                                vault_number=registry.vault_number,
                                shelf_number=shelf_number,
                                reason=event,
                            )
                        elif event == "ASSIGNMENT_LOOKUP_FAILED":
                            print(
                                f"[{time.strftime('%H:%M:%S')}] WARNING_ASSIGNMENT_LOOKUP_FAILED "
                                f"picked={details['picked']} reason={details['reason']}"
                            )
                            event_publisher.publish(
                                "WARNING_ASSIGNMENT_LOOKUP_FAILED",
                                tray_label=label,
                                vault_number=registry.vault_number,
                                shelf_number=shelf_number,
                                picked=details["picked"],
                                reason=details["reason"],
                            )
                        else:
                            print(
                                f"[{time.strftime('%H:%M:%S')}] NOTICE_TRAY_ON_TABLE_WITHOUT_OBSERVED_PICKUP "
                                f"tray={label}"
                            )
                            event_publisher.publish(
                                "NOTICE_TRAY_ON_TABLE_WITHOUT_OBSERVED_PICKUP",
                                tray_label=label,
                                vault_number=registry.vault_number,
                                shelf_number=shelf_number,
                            )

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
            return "quit"

        now = time.monotonic()
        elapsed = now - stats_window_start
        if elapsed >= STATS_INTERVAL:
            fps = frames_captured / elapsed
            cpu_now, rss_mb = proc_stats()
            system_idle_now, system_total_now = system_cpu_times()
            mem_available_mb, mem_used_pct, cpu_temp_c, throttled_hex = system_stats()
            if cpu_now is not None and stats_cpu_start is not None:
                cpu_pct = 100 * (cpu_now - stats_cpu_start) / elapsed
                cpu_str = f"{cpu_pct:.1f}%"
            else:
                cpu_pct = None
                cpu_str = "n/a"
            if (
                system_idle_now is not None
                and system_idle_start is not None
                and system_total_now - system_total_start > 0
            ):
                system_cpu_pct = 100 * (
                    1 - (system_idle_now - system_idle_start) / (system_total_now - system_total_start)
                )
                system_cpu_str = f"{system_cpu_pct:.1f}%"
            else:
                system_cpu_pct = None
                system_cpu_str = "n/a"
            rss_str = f"{rss_mb:.1f}MB" if rss_mb is not None else "n/a"
            mem_avail_str = f"{mem_available_mb:.0f}MB" if mem_available_mb is not None else "n/a"
            mem_used_str = f"{mem_used_pct:.1f}%" if mem_used_pct is not None else "n/a"
            temp_str = f"{cpu_temp_c:.1f}C" if cpu_temp_c is not None else "n/a"

            def _latency_str(times):
                if not times:
                    return "calls=0"
                return (
                    f"calls={len(times)} avg={sum(times) / len(times):.1f}ms "
                    f"min={min(times):.1f}ms max={max(times):.1f}ms"
                )

            def _latency_agg(times):
                if not times:
                    return 0, None, None, None
                return len(times), sum(times) / len(times), min(times), max(times)

            print(
                f"[{time.strftime('%H:%M:%S')}] STATS window={elapsed:.1f}s fps={fps:.1f} "
                f"cpu={cpu_str} system_cpu={system_cpu_str} rss={rss_str} "
                f"mem_available={mem_avail_str} mem_used={mem_used_str} "
                f"cpu_temp={temp_str} throttled={throttled_hex or 'n/a'} "
                f"frames={frames_captured} grab_fails={grab_fails} motion_skips={motion_skips} "
                f"aruco({_latency_str(aruco_times)}) yolo({_latency_str(yolo_times)})"
            )

            aruco_calls, aruco_avg, aruco_min, aruco_max = _latency_agg(aruco_times)
            yolo_calls, yolo_avg, yolo_min, yolo_max = _latency_agg(yolo_times)
            stats_csv.writerow(
                [
                    time.strftime("%Y-%m-%d %H:%M:%S"),
                    f"{elapsed:.1f}",
                    f"{fps:.1f}",
                    f"{cpu_pct:.1f}" if cpu_pct is not None else "",
                    f"{system_cpu_pct:.1f}" if system_cpu_pct is not None else "",
                    f"{rss_mb:.1f}" if rss_mb is not None else "",
                    f"{mem_available_mb:.0f}" if mem_available_mb is not None else "",
                    f"{mem_used_pct:.1f}" if mem_used_pct is not None else "",
                    f"{cpu_temp_c:.1f}" if cpu_temp_c is not None else "",
                    throttled_hex or "",
                    frames_captured,
                    grab_fails,
                    motion_skips,
                    aruco_calls,
                    f"{aruco_avg:.1f}" if aruco_avg is not None else "",
                    f"{aruco_min:.1f}" if aruco_min is not None else "",
                    f"{aruco_max:.1f}" if aruco_max is not None else "",
                    yolo_calls,
                    f"{yolo_avg:.1f}" if yolo_avg is not None else "",
                    f"{yolo_min:.1f}" if yolo_min is not None else "",
                    f"{yolo_max:.1f}" if yolo_max is not None else "",
                ]
            )
            stats_log_file.flush()
            os.fsync(stats_log_file.fileno())

            stats_window_start = now
            stats_cpu_start = cpu_now
            system_idle_start, system_total_start = system_idle_now, system_total_now
            frames_captured = 0
            grab_fails = 0
            motion_skips = 0
            aruco_times = []
            yolo_times = []

        time.sleep(CAPTURE_LOOP_DELAY)


def main():
    args = parse_args()
    source = parse_camera_source(args.cam) if args.cam is not None else CAMERA_SOURCE
    recording_active = RECORDING_ENABLED and is_local_device(source)

    detector = ArucoDetector()
    open_close_detector = OpenCloseDetector()
    print(f"Loaded open/close model, device={open_close_detector.device}")
    registry = TrayRegistry()
    print(f"Loaded tray registry for {registry.branch_id}: {registry.registered_labels()}")
    zones = ZoneChecker()
    print(f"Loaded zone config for {zones.branch_id}")
    tray_state_machine = TrayStateMachine()
    aurus_guard_client = AurusGuardClient()
    event_publisher = EventPublisher()

    streamer = None
    window_name = None
    if args.display:
        window_name = "Vault Tracker - Step 2 (press q to quit)"
        cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
        cv2.moveWindow(window_name, 100, 100)
        cv2.resizeWindow(window_name, 960, 540)
        print("Press 'q' in the video window (or Ctrl+C here) to stop.")
        print("If you don't see the window, check Cmd+Tab / other desktops — it opens at (100, 100).")
    elif args.stream:
        streamer = MJPEGStreamer(port=args.stream_port)
        streamer.start()
        print("Ctrl+C here to stop.")
    else:
        print("Logs-only (no --display/--stream). Ctrl+C here to stop.")

    print(
        f"CONFIG frame={FRAME_WIDTH}x{FRAME_HEIGHT} aruco_interval={ARUCO_FRAME_INTERVAL} "
        f"yolo_interval={YOLO_FRAME_INTERVAL} yolo_imgsz={OPEN_CLOSE_IMG_SIZE} "
        f"yolo_model={OPEN_CLOSE_MODEL_PATH} motion_gating={MOTION_GATING_ENABLED} "
        f"motion_threshold={MOTION_THRESHOLD} capture_delay={CAPTURE_LOOP_DELAY} "
        f"recording={'on' if recording_active else 'off'}"
    )

    stats_log_is_new = not os.path.exists(STATS_LOG_PATH) or os.path.getsize(STATS_LOG_PATH) == 0
    stats_log_file = open(STATS_LOG_PATH, "a", newline="")
    stats_csv = csv.writer(stats_log_file)
    if stats_log_is_new:
        stats_csv.writerow(
            [
                "timestamp", "elapsed_s", "fps", "cpu_pct", "system_cpu_pct", "rss_mb",
                "mem_available_mb", "mem_used_pct", "cpu_temp_c", "throttled_hex",
                "frames", "grab_fails", "motion_skips",
                "aruco_calls", "aruco_avg_ms", "aruco_min_ms", "aruco_max_ms",
                "yolo_calls", "yolo_avg_ms", "yolo_min_ms", "yolo_max_ms",
            ]
        )
        stats_log_file.flush()
    print(f"Logging periodic CPU/RAM/latency stats to {STATS_LOG_PATH}")

    upload_worker = None
    if recording_active:
        upload_worker = UploadWorker(
            RECORDINGS_DIR, DRIVE_REMOTE, RECORDING_MIN_UPLOAD_AGE_SECONDS, RECORDING_UPLOAD_INTERVAL_SECONDS
        )
        upload_worker.start()
        print(
            f"Recording enabled: segments -> {RECORDINGS_DIR}, uploads -> {DRIVE_REMOTE}, "
            f"active hours {ACTIVE_HOURS_START}-{ACTIVE_HOURS_END}"
        )

    detection_loop_kwargs = dict(
        streamer=streamer,
        args=args,
        window_name=window_name,
        detector=detector,
        open_close_detector=open_close_detector,
        registry=registry,
        zones=zones,
        tray_state_machine=tray_state_machine,
        aurus_guard_client=aurus_guard_client,
        event_publisher=event_publisher,
        stats_csv=stats_csv,
        stats_log_file=stats_log_file,
    )

    try:
        if recording_active:
            while True:
                now = datetime.datetime.now()
                if not is_active_hours(now):
                    wait_until = next_active_window_start(now)
                    print(
                        f"[{time.strftime('%H:%M:%S')}] Outside active hours, "
                        f"sleeping until {wait_until.strftime('%Y-%m-%d %H:%M:%S')}"
                    )
                    time.sleep(min(60.0, max(1.0, (wait_until - now).total_seconds())))
                    continue

                session_end = datetime.datetime.combine(now.date(), ACTIVE_HOURS_END)
                stop_at = time.monotonic() + (session_end - now).total_seconds()
                device = to_v4l2_device_path(source)
                print(
                    f"Opening camera device: {device!r} (recording session, "
                    f"ends {session_end.strftime('%H:%M:%S')})"
                )
                cap = FfmpegDualOutputCapture(
                    device=device,
                    recordings_dir=RECORDINGS_DIR,
                    width=RECORDING_WIDTH,
                    height=RECORDING_HEIGHT,
                    segment_seconds=RECORDING_SEGMENT_SECONDS,
                    bitrate=RECORDING_BITRATE,
                    camera_controls={
                        "auto_exposure": CAMERA_AUTO_EXPOSURE,
                        "brightness": CAMERA_BRIGHTNESS,
                    },
                )
                cap.open()
                try:
                    reason = detection_loop(cap, stop_at=stop_at, **detection_loop_kwargs)
                finally:
                    cap.release()

                if reason == "quit":
                    break
                # "deadline" or "cap_lost": loop back around, re-check active
                # hours and reopen the camera.
        else:
            print(f"Opening camera source: {source!r}")
            cap = open_camera(source)
            try:
                detection_loop(cap, stop_at=None, **detection_loop_kwargs)
            finally:
                cap.release()
    finally:
        if args.display:
            cv2.destroyAllWindows()
        if streamer is not None:
            streamer.stop()
        if upload_worker is not None:
            upload_worker.stop()
        stats_log_file.close()
        event_publisher.close()


if __name__ == "__main__":
    main()
