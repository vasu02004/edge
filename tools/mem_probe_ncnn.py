"""RSS probe for the raw-ncnn inference path (no torch/ultralytics), to compare
against tools/mem_probe.py and quantify what dropping ultralytics would save.

Run with: python tools/mem_probe_ncnn.py
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

import ncnn  # noqa: E402

checkpoint("after import ncnn (no torch)")

net = ncnn.Net()
net.load_param("models/yolo26n_best_ncnn_model/model.ncnn.param")
net.load_model("models/yolo26n_best_ncnn_model/model.ncnn.bin")
checkpoint("after net.load_param/load_model")

img = np.zeros((3, 320, 320), dtype=np.float32)
for _ in range(21):
    with net.create_extractor() as ex:
        ex.input("in0", ncnn.Mat(img).clone())
        _, out0 = ex.extract("out0")
        _ = np.array(out0)
checkpoint("after 21 extractor runs (plateau check)")

print(f"\nTOTAL RSS: {rss_mb():.1f}MB")
