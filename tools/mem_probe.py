"""Standalone RSS probe for the OLD ultralytics.YOLO-based detector — kept as
a reference point for the ~430MB baseline that detection/open_close_detector.py
no longer pays now that it calls ncnn directly (see tools/mem_probe_ncnn.py
for the current path's numbers, ~80MB).

torch/torchvision/ultralytics are no longer in requirements.txt; install
requirements-export.txt to run this.

Run with: python tools/mem_probe.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def rss_mb():
    with open("/proc/self/status") as f:
        for line in f:
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) / 1024
    return None


_last = [0.0]


def checkpoint(label):
    if rss_mb() is None:
        print(f"{label:45s} rss=n/a (not Linux/proc)")
        return
    now = rss_mb()
    delta = now - _last[0]
    print(f"{label:45s} rss={now:8.1f}MB  (+{delta:.1f}MB)")
    _last[0] = now


checkpoint("baseline (python interpreter)")

import numpy as np  # noqa: E402

checkpoint("after import numpy")

import cv2  # noqa: E402

checkpoint("after import cv2 (opencv-contrib)")

_ = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_6X6_250)
checkpoint("after cv2.aruco dictionary init")

import torch  # noqa: E402

checkpoint("after import torch")

import torchvision  # noqa: E402

checkpoint("after import torchvision")

from ultralytics import YOLO  # noqa: E402

checkpoint("after import ultralytics.YOLO")

from config import OPEN_CLOSE_IMG_SIZE, OPEN_CLOSE_MODEL_PATH  # noqa: E402

print(f"\nLoading model from OPEN_CLOSE_MODEL_PATH={OPEN_CLOSE_MODEL_PATH!r}")
model = YOLO(OPEN_CLOSE_MODEL_PATH)
checkpoint("after YOLO(model_path) load")

model.predict(
    np.zeros((OPEN_CLOSE_IMG_SIZE, OPEN_CLOSE_IMG_SIZE, 3), dtype=np.uint8),
    imgsz=OPEN_CLOSE_IMG_SIZE, conf=0.5, device="cpu", verbose=False,
)
checkpoint("after first predict() (graph build/warmup)")

for _ in range(20):
    model.predict(
        np.zeros((OPEN_CLOSE_IMG_SIZE, OPEN_CLOSE_IMG_SIZE, 3), dtype=np.uint8),
        imgsz=OPEN_CLOSE_IMG_SIZE, conf=0.5, device="cpu", verbose=False,
    )
checkpoint("after 20 more predict() calls (plateau check)")

print(f"\nTOTAL RSS: {rss_mb():.1f}MB")
