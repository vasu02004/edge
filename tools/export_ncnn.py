import argparse
import sys
from pathlib import Path

from ultralytics import YOLO

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import OPEN_CLOSE_IMG_SIZE, OPEN_CLOSE_MODEL_PATH


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=OPEN_CLOSE_MODEL_PATH)
    parser.add_argument("--imgsz", type=int, default=OPEN_CLOSE_IMG_SIZE)
    return parser.parse_args()


def main():
    args = parse_args()
    model = YOLO(args.model)
    out_dir = model.export(format="ncnn", imgsz=args.imgsz)
    print(f"Exported ncnn model to: {out_dir}")
    print(f"Set OPEN_CLOSE_MODEL_PATH={out_dir} in your .env to use it.")


if __name__ == "__main__":
    main()
