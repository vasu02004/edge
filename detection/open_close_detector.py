import torch
from ultralytics import YOLO

from config import OPEN_CLOSE_CONF_THRESHOLD, OPEN_CLOSE_IMG_SIZE, OPEN_CLOSE_MODEL_PATH


def _select_device():
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


class OpenCloseDetector:
    def __init__(
        self,
        model_path: str = OPEN_CLOSE_MODEL_PATH,
        conf: float = OPEN_CLOSE_CONF_THRESHOLD,
        img_size: int = OPEN_CLOSE_IMG_SIZE,
    ):
        self.device = _select_device()
        self.model = YOLO(model_path)
        self.conf = conf
        self.img_size = img_size

    def detect(self, frame):
        result = self.model.predict(
            frame, imgsz=self.img_size, conf=self.conf, device=self.device, verbose=False
        )[0]
        detections = []
        for box in result.boxes:
            x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
            label = result.names[int(box.cls[0])]
            confidence = float(box.conf[0])
            detections.append({"label": label, "confidence": confidence, "box": (x1, y1, x2, y2)})
        return detections
