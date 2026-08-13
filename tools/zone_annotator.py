import argparse
import json
import os
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from camera.capture import open_camera
from config import BRANCH_ID, CAMERA_SOURCE, ZONE_CONFIG_PATH, parse_camera_source
from tools.zone_state import ZoneAnnotatorState

ZONE_NAMES = ["vault_zone", "table_zone", "boundary"]
ZONE_COLORS = {
    "vault_zone": (0, 165, 255),
    "table_zone": (255, 0, 255),
    "boundary": (255, 255, 0),
}


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cam", default=None, help="Camera source override (device index or URL)")
    parser.add_argument("--image", default=None, help="Use a saved image file instead of the live camera")
    parser.add_argument("--out", default=ZONE_CONFIG_PATH, help="Output zone config JSON path")
    return parser.parse_args()


def grab_reference_frame(image_path, cam_source):
    if image_path:
        frame = cv2.imread(image_path)
        if frame is None:
            raise RuntimeError(f"Could not read image: {image_path}")
        return frame
    cap = open_camera(cam_source)
    ok, frame = cap.read()
    cap.release()
    if not ok:
        raise RuntimeError("Could not grab a frame from the camera")
    return frame


def render(frame, state):
    display = frame.copy()
    for name in state.zone_names:
        pts = state.points_for(name)
        color = ZONE_COLORS[name]
        if len(pts) >= 2:
            cv2.polylines(
                display,
                [np.array(pts, dtype=np.int32)],
                isClosed=len(pts) >= 3,
                color=color,
                thickness=2,
            )
        for p in pts:
            cv2.circle(display, tuple(p), 5, color, -1)

    current = state.current_zone_name
    status = f"Drawing: {current} (click points, 'n' when done)" if current else "All zones done — press 's' to save"
    cv2.rectangle(display, (0, 0), (display.shape[1], 40), (0, 0, 0), -1)
    cv2.putText(display, status, (10, 27), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    return display


def main():
    args = parse_args()
    cam_source = parse_camera_source(args.cam) if args.cam is not None else CAMERA_SOURCE
    frame = grab_reference_frame(args.image, cam_source)

    out_dir = os.path.dirname(args.out) or "."
    os.makedirs(out_dir, exist_ok=True)
    reference_path = os.path.join(out_dir, f"{BRANCH_ID}_reference.jpg")
    cv2.imwrite(reference_path, frame)
    print(f"Saved reference frame -> {reference_path}")

    state = ZoneAnnotatorState(ZONE_NAMES)
    window = "Zone Annotator"
    cv2.namedWindow(window, cv2.WINDOW_NORMAL)
    cv2.moveWindow(window, 100, 100)

    def on_mouse(event, x, y, _flags, _userdata):
        if event == cv2.EVENT_LBUTTONDOWN:
            state.add_point(x, y)

    cv2.setMouseCallback(window, on_mouse)

    print("Click to add polygon points for each zone.")
    print("Keys: n = finish current zone / next zone | u = undo last point | s = save | q = quit without saving")

    while True:
        cv2.imshow(window, render(frame, state))
        key = cv2.waitKey(20) & 0xFF

        if key == ord("n"):
            if not state.finish_current_zone():
                print("Need at least 3 points before moving to the next zone.")
        elif key == ord("u"):
            state.undo_last_point()
        elif key == ord("s"):
            if not state.is_complete():
                print("Finish all zones (press 'n' after each) before saving.")
                continue
            with open(args.out, "w") as f:
                json.dump(state.to_dict(BRANCH_ID), f, indent=2)
            print(f"Saved zone config -> {args.out}")
            break
        elif key == ord("q"):
            print("Quit without saving.")
            break

    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
