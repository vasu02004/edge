"""
Probe camera indices 0-5, save one snapshot from each that opens, so you can
visually tell which index is your laptop webcam vs DroidCam.
"""

import os

import cv2

OUT_DIR = "camera_probe"


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    found = []
    for idx in range(6):
        cap = cv2.VideoCapture(idx)
        if not cap.isOpened():
            cap.release()
            continue
        ok, frame = cap.read()
        cap.release()
        if not ok:
            continue
        path = os.path.join(OUT_DIR, f"index_{idx}.jpg")
        cv2.imwrite(path, frame)
        h, w = frame.shape[:2]
        found.append(idx)
        print(f"index {idx}: opened, frame {w}x{h}, saved snapshot -> {path}")

    if not found:
        print("No camera indices opened successfully (0-5).")
        print("If using DroidCam over WiFi/network mode, set CAMERA_SOURCE to its stream URL instead, e.g.:")
        print("  CAMERA_SOURCE=http://<phone-ip>:4747/video python main.py")
    else:
        print(f"\nOpen the images in {OUT_DIR}/ and check which one shows your phone's (DroidCam) view.")
        print("Then set CAMERA_SOURCE to that index before running main.py, e.g.:")
        print(f"  CAMERA_SOURCE={found[0]} python main.py")


if __name__ == "__main__":
    main()
