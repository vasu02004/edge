import argparse
import time

import cv2

from camera.capture import open_camera
from config import CAMERA_SOURCE, parse_camera_source
from aurus_guard.client import AurusGuardClient
from detection.aruco_detector import ArucoDetector
from detection.zones import ZoneChecker
from registry.tray_registry import TrayRegistry
from state_machine.rules import check_wrong_tray
from state_machine.tray_state import TRAY_PICKED, TrayStateMachine

RED = "\033[91m"
RESET = "\033[0m"

ZONE_DRAW_COLORS = {
    "vault_zone": (0, 165, 255),
    "table_zone": (255, 0, 255),
    "boundary": (255, 255, 0),
}


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--cam",
        default=None,
        help="Camera source: device index (e.g. 1) or stream URL (e.g. http://<ip>:4747/mjpegfeed). "
        "Overrides the CAMERA_SOURCE env var if given.",
    )
    return parser.parse_args()


def annotate(frame, registered_detections, zones):
    annotated = frame.copy()

    for zone_name, color in ZONE_DRAW_COLORS.items():
        polygon = zones.polygon(zone_name)
        if polygon is not None:
            thickness = 2 if zone_name == "boundary" else 1
            cv2.polylines(annotated, [polygon], True, color, thickness)

    for d in registered_detections:
        pts = d["corners"].astype(int)
        cv2.polylines(annotated, [pts], True, (0, 255, 0), 2)
        cx, cy = d["centroid"]
        cv2.circle(annotated, (int(cx), int(cy)), 4, (0, 0, 255), -1)
        cv2.putText(
            annotated,
            f"{d['tray_label']} (id={d['id']}) [{d['zone']}] {d['state']}",
            (int(cx) + 8, int(cy)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 255, 0),
            2,
        )
    return annotated


def main():
    args = parse_args()
    source = parse_camera_source(args.cam) if args.cam is not None else CAMERA_SOURCE
    print(f"Opening camera source: {source!r}")
    cap = open_camera(source)
    detector = ArucoDetector()
    registry = TrayRegistry()
    print(f"Loaded tray registry for {registry.branch_id}: {registry.registered_labels()}")
    zones = ZoneChecker()
    print(f"Loaded zone config for {zones.branch_id}")
    tray_state_machine = TrayStateMachine()
    aurus_guard_client = AurusGuardClient()

    window_name = "Vault Tracker - Step 2 (press q to quit)"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    cv2.moveWindow(window_name, 100, 100)
    cv2.resizeWindow(window_name, 960, 540)

    print("Camera opened. Press 'q' in the video window (or Ctrl+C here) to stop.")
    print("If you don't see the window, check Cmd+Tab / other desktops — it opens at (100, 100).")
    try:
        first_frame = True
        while True:
            ok, frame = cap.read()
            if not ok:
                print("Frame grab failed, retrying...")
                time.sleep(0.1)
                continue

            detections = detector.detect(frame)
            registered = []
            for d in detections:
                label = registry.label_for(d["id"])
                if label is None:
                    continue
                d["tray_label"] = label
                zone = zones.classify(d["centroid"])
                d["zone"] = zone
                registered.append(d)

                cx, cy = d["centroid"]
                print(
                    f"[{time.strftime('%H:%M:%S')}] tray={label} zone={zone} marker_id={d['id']} "
                    f"centroid=({cx:.1f}, {cy:.1f}) corners={d['corners'].tolist()}"
                )

                if not zones.is_within_boundary(d["centroid"]):
                    print(f"[{time.strftime('%H:%M:%S')}] EVENT_CROSSED_BOUNDARY tray={label}")

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

            cv2.imshow(window_name, annotate(frame, registered, zones))
            if first_frame:
                cv2.setWindowProperty(window_name, cv2.WND_PROP_TOPMOST, 1)
                first_frame = False
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    finally:
        cap.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
