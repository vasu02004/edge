import cv2
import ncnn
import numpy as np

from config import OPEN_CLOSE_CONF_THRESHOLD, OPEN_CLOSE_IMG_SIZE, OPEN_CLOSE_IOU_THRESHOLD, OPEN_CLOSE_MODEL_PATH

# The exported ncnn graph already bakes in anchor generation, box regression
# decode (dist2bbox), stride scaling, and the class-score sigmoid — out0 is
# (4 + num_classes, num_anchors): [cx, cy, w, h, score_0, score_1, ...] in
# pixel coordinates of the letterboxed model input. Only letterbox
# preprocessing, confidence filtering, NMS, and box rescaling happen here.
# Calling ncnn directly (instead of via ultralytics.YOLO) avoids importing
# torch/torchvision, which cost ~350MB RSS purely for pre/postprocessing glue
# ultralytics did around the same underlying graph. Verified numerically
# equivalent to ultralytics' own decode/NMS in tools/validate_ncnn_decoder.py.
_PAD_COLOR = (114, 114, 114)


def _letterbox(frame, new_size):
    h, w = frame.shape[:2]
    r = min(new_size / h, new_size / w)
    new_unpad_w, new_unpad_h = round(w * r), round(h * r)
    dw, dh = (new_size - new_unpad_w) / 2, (new_size - new_unpad_h) / 2

    if (w, h) != (new_unpad_w, new_unpad_h):
        frame = cv2.resize(frame, (new_unpad_w, new_unpad_h), interpolation=cv2.INTER_LINEAR)

    top, bottom = round(dh - 0.1), round(dh + 0.1)
    left, right = round(dw - 0.1), round(dw + 0.1)
    padded = cv2.copyMakeBorder(frame, top, bottom, left, right, cv2.BORDER_CONSTANT, value=_PAD_COLOR)
    return padded, r, left, top


class OpenCloseDetector:
    LABELS = {0: "closed", 1: "open"}

    def __init__(
        self,
        model_path: str = OPEN_CLOSE_MODEL_PATH,
        conf: float = OPEN_CLOSE_CONF_THRESHOLD,
        iou: float = OPEN_CLOSE_IOU_THRESHOLD,
        img_size: int = OPEN_CLOSE_IMG_SIZE,
    ):
        self.device = "cpu"
        self.conf = conf
        self.iou = iou
        self.img_size = img_size

        self.net = ncnn.Net()
        # Pi 4 has 4 cores; uncapped, ncnn sizes its thread pool off the
        # host's core count, which can exceed a container's --cpus quota.
        self.net.opt.num_threads = 4
        self.net.load_param(f"{model_path}/model.ncnn.param")
        self.net.load_model(f"{model_path}/model.ncnn.bin")

        # ncnn lazily builds/optimizes the inference graph on its first call
        # (multi-second stall) rather than at load time — force that here so
        # it happens during startup, not on the first live frame.
        self.detect(np.zeros((img_size, img_size, 3), dtype=np.uint8))

    def _infer(self, chw):
        with self.net.create_extractor() as ex:
            ex.input("in0", ncnn.Mat(chw).clone())
            _, out0 = ex.extract("out0")
            return np.array(out0)

    def detect(self, frame):
        frame_h, frame_w = frame.shape[:2]
        padded, ratio, pad_left, pad_top = _letterbox(frame, self.img_size)
        rgb = cv2.cvtColor(padded, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        chw = np.ascontiguousarray(rgb.transpose(2, 0, 1))

        raw = self._infer(chw)  # (4 + num_classes, num_anchors)
        preds = raw.T  # (num_anchors, 4 + num_classes)

        boxes_cxcywh = preds[:, :4]
        scores = preds[:, 4:]
        class_ids = np.argmax(scores, axis=1)
        confidences = scores[np.arange(len(scores)), class_ids]

        keep = confidences >= self.conf
        if not np.any(keep):
            return []

        boxes_cxcywh = boxes_cxcywh[keep]
        class_ids = class_ids[keep]
        confidences = confidences[keep]

        # cv2.dnn.NMSBoxes wants (x, y, w, h) with x, y = top-left corner.
        boxes_xywh = np.empty_like(boxes_cxcywh)
        boxes_xywh[:, 0] = boxes_cxcywh[:, 0] - boxes_cxcywh[:, 2] / 2
        boxes_xywh[:, 1] = boxes_cxcywh[:, 1] - boxes_cxcywh[:, 3] / 2
        boxes_xywh[:, 2] = boxes_cxcywh[:, 2]
        boxes_xywh[:, 3] = boxes_cxcywh[:, 3]

        detections = []
        for class_id in np.unique(class_ids):
            mask = class_ids == class_id
            idxs = cv2.dnn.NMSBoxes(
                boxes_xywh[mask].tolist(),
                confidences[mask].tolist(),
                self.conf,
                self.iou,
            )
            for i in np.array(idxs).reshape(-1):
                x, y, w, h = boxes_xywh[mask][i]
                x1 = np.clip((x - pad_left) / ratio, 0, frame_w)
                y1 = np.clip((y - pad_top) / ratio, 0, frame_h)
                x2 = np.clip((x + w - pad_left) / ratio, 0, frame_w)
                y2 = np.clip((y + h - pad_top) / ratio, 0, frame_h)
                detections.append(
                    {
                        "label": self.LABELS.get(int(class_id), str(class_id)),
                        "confidence": float(confidences[mask][i]),
                        "box": (int(x1), int(y1), int(x2), int(y2)),
                    }
                )
        return detections
