"""Validation harness (dev-only, not shipped): confirms the hand-rolled
raw-ncnn decode in detection/open_close_detector_ncnn.py produces the same
boxes/scores as the current ultralytics.YOLO pipeline, before it replaces it.

Compares pre-NMS raw candidate boxes (very low conf threshold) at the pixel
level in original-frame coordinates, since we don't have a real photo with an
open/close tray to compare final high-confidence detections against.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cv2
import numpy as np
from ultralytics import YOLO

from detection.open_close_detector import OpenCloseDetector

IMG_SIZE = 320
LOW_CONF = 0.001

frame = cv2.imread("zone_config/branch_001_reference.jpg")
print("frame shape:", frame.shape)

# Reference: ultralytics running the SAME ncnn weights via its own ncnn backend —
# isolates postprocessing (letterbox/NMS/rescale) differences from any .pt-vs-ncnn
# numerical precision differences in the model itself.
ref_model = YOLO("models/yolo26n_best_ncnn_model")
ref_result = ref_model.predict(
    frame, imgsz=IMG_SIZE, conf=LOW_CONF, iou=0.45, device="cpu", verbose=False
)[0]
ref_boxes = []
for box in ref_result.boxes:
    x1, y1, x2, y2 = map(float, box.xyxy[0].tolist())
    ref_boxes.append(
        {
            "label": ref_result.names[int(box.cls[0])],
            "confidence": float(box.conf[0]),
            "box": (x1, y1, x2, y2),
        }
    )
ref_boxes.sort(key=lambda d: -d["confidence"])
print(f"\nREFERENCE (ultralytics) {len(ref_boxes)} candidate boxes @ conf>={LOW_CONF}:")
for b in ref_boxes[:10]:
    print(f"  {b['label']:8s} conf={b['confidence']:.4f} box={tuple(round(v, 1) for v in b['box'])}")

# Candidate: hand-rolled raw ncnn decode.
new_detector = OpenCloseDetector(
    model_path="models/yolo26n_best_ncnn_model", conf=LOW_CONF, iou=0.45, img_size=IMG_SIZE
)
new_boxes = new_detector.detect(frame)
new_boxes.sort(key=lambda d: -d["confidence"])
print(f"\nCANDIDATE (raw ncnn) {len(new_boxes)} candidate boxes @ conf>={LOW_CONF}:")
for b in new_boxes[:10]:
    print(f"  {b['label']:8s} conf={b['confidence']:.4f} box={tuple(round(v, 1) for v in b['box'])}")


def match(ref, cand_list, used, iou_thresh=0.5, conf_tol=0.05):
    bx1, by1, bx2, by2 = ref["box"]
    best_i, best_iou = None, 0.0
    for i, c in enumerate(cand_list):
        if i in used or c["label"] != ref["label"]:
            continue
        cx1, cy1, cx2, cy2 = c["box"]
        ix1, iy1 = max(bx1, cx1), max(by1, cy1)
        ix2, iy2 = min(bx2, cx2), min(by2, cy2)
        iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
        inter = iw * ih
        union = (bx2 - bx1) * (by2 - by1) + (cx2 - cx1) * (cy2 - cy1) - inter
        iou = inter / union if union > 0 else 0
        if iou > best_iou:
            best_iou, best_i = iou, i
    if best_i is not None and best_iou >= iou_thresh:
        conf_diff = abs(cand_list[best_i]["confidence"] - ref["confidence"])
        return best_i, best_iou, conf_diff
    return None, best_iou, None


print("\nMATCHING (top 10 reference boxes vs candidates, IoU>=0.5):")
used = set()
n_ok = 0
for ref in ref_boxes[:10]:
    idx, iou, conf_diff = match(ref, new_boxes, used)
    if idx is not None:
        used.add(idx)
        ok = conf_diff < 0.05
        n_ok += ok
        print(
            f"  OK  iou={iou:.3f} conf_diff={conf_diff:.4f} "
            f"ref=({ref['label']},{ref['confidence']:.3f}) "
            f"cand=({new_boxes[idx]['label']},{new_boxes[idx]['confidence']:.3f})"
        )
    else:
        print(f"  MISS ref=({ref['label']},{ref['confidence']:.3f}) box={ref['box']} best_iou={iou:.3f}")

print(f"\n{n_ok}/{min(10, len(ref_boxes))} reference boxes matched within tolerance.")
