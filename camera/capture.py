import urllib.request

import cv2
import numpy as np

from config import CAMERA_SOURCE, FRAME_HEIGHT, FRAME_WIDTH


def _candidate_urls(url: str) -> list:
    base = url.split("/mjpegfeed")[0].split("/video")[0].rstrip("/")
    candidates = [url, f"{base}/mjpegfeed", f"{base}/video"]
    seen = set()
    ordered = []
    for u in candidates:
        if u not in seen:
            seen.add(u)
            ordered.append(u)
    return ordered


class MjpegHttpStream:
    """Manual MJPEG-over-HTTP reader for streams cv2.VideoCapture can't parse
    (DroidCam's raw multipart stream is a common case). Mimics the subset of
    cv2.VideoCapture's interface main.py relies on: read() -> (ok, frame),
    release().
    """

    def __init__(self, url: str, timeout: float = 5.0):
        self._stream = None
        self._buffer = b""
        last_error = None
        for candidate in _candidate_urls(url):
            try:
                req = urllib.request.Request(candidate, headers={"User-Agent": "Mozilla/5.0"})
                self._stream = urllib.request.urlopen(req, timeout=timeout)
                print(f"Connected to MJPEG stream: {candidate}")
                break
            except Exception as e:
                last_error = e
        if self._stream is None:
            raise RuntimeError(f"Could not connect to any MJPEG endpoint for {url!r}: {last_error}")

    def isOpened(self):
        return self._stream is not None

    def read(self):
        try:
            while True:
                start = self._buffer.find(b"\xff\xd8")
                end = self._buffer.find(b"\xff\xd9", start + 2) if start != -1 else -1
                if start != -1 and end != -1:
                    jpg = self._buffer[start : end + 2]
                    self._buffer = self._buffer[end + 2 :]
                    frame = cv2.imdecode(np.frombuffer(jpg, dtype=np.uint8), cv2.IMREAD_COLOR)
                    if frame is not None:
                        return True, frame
                    continue  # corrupt chunk, discard and keep scanning
                chunk = self._stream.read(4096)
                if not chunk:
                    return False, None
                self._buffer += chunk
        except Exception:
            return False, None

    def release(self):
        try:
            if self._stream:
                self._stream.close()
        except Exception:
            pass


def open_camera(source=None):
    source = CAMERA_SOURCE if source is None else source

    if isinstance(source, str) and source.startswith(("http://", "https://")):
        cap = cv2.VideoCapture(source)
        if cap.isOpened():
            ok, _ = cap.read()
            if ok:
                return cap
            cap.release()
        # cv2's FFmpeg backend can't parse DroidCam's raw MJPEG stream on this
        # system — fall back to a manual byte-scanning JPEG reader.
        stream = MjpegHttpStream(source)
        if not stream.isOpened():
            raise RuntimeError(f"Could not open camera source: {source!r}")
        return stream

    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        raise RuntimeError(f"Could not open camera source: {source!r}")
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)
    return cap
