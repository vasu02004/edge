import collections
import logging
import os
import subprocess
import threading
import time

import cv2
import numpy as np

from camera.jpeg_stream import JpegFrameSplitter

log = logging.getLogger("camera.ffmpeg_capture")


def _set_camera_controls(device, controls):
    for name, value in controls.items():
        result = subprocess.run(
            ["v4l2-ctl", "-d", device, f"--set-ctrl={name}={value}"],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            log.warning("Failed to set %s=%s: %s", name, value, result.stderr.strip())


def _upload_finished_segments(recordings_dir, drive_remote, min_age_seconds):
    now = time.time()
    for name in sorted(os.listdir(recordings_dir)):
        if not name.endswith(".mp4"):
            continue
        path = os.path.join(recordings_dir, name)
        age = now - os.path.getmtime(path)
        if age < min_age_seconds:
            continue  # still being written by ffmpeg
        log.info("Uploading %s (age %.0fs)", name, age)
        result = subprocess.run(
            ["rclone", "moveto", path, f"{drive_remote}{name}"],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            log.info("Uploaded and removed %s", name)
        else:
            log.error("Upload failed for %s: %s", name, result.stderr.strip())


class UploadWorker:
    """Background thread that periodically uploads finished recording segments.
    Runs for the whole process lifetime, independent of camera sessions, so a
    segment that closes right as an active-hours session ends still gets
    uploaded."""

    def __init__(self, recordings_dir, drive_remote, min_age_seconds, interval_seconds):
        self._recordings_dir = recordings_dir
        self._drive_remote = drive_remote
        self._min_age_seconds = min_age_seconds
        self._interval_seconds = interval_seconds
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        os.makedirs(self._recordings_dir, exist_ok=True)
        self._thread.start()

    def _run(self):
        while not self._stop_event.wait(self._interval_seconds):
            try:
                _upload_finished_segments(self._recordings_dir, self._drive_remote, self._min_age_seconds)
            except OSError as e:
                log.error("Upload sweep failed: %s", e)

    def stop(self):
        self._stop_event.set()
        self._thread.join(timeout=self._interval_seconds + 5)


class FfmpegDualOutputCapture:
    """Opens a local v4l2 camera device through a single ffmpeg process that fans
    out to two outputs: a hardware-encoded (h264_v4l2m2m) segmented MP4
    recording on disk, and an MJPEG copy piped to this process's stdout for the
    detection pipeline to decode. The mjpeg leg is a codec copy (no re-encode),
    so the only real encoding cost is the hardware-accelerated recording leg --
    this is meant to be the sole consumer of the device; running anything else
    against the same device at the same time will fail to open it.
    """

    def __init__(
        self,
        device,
        recordings_dir,
        width=1920,
        height=1080,
        segment_seconds=900,
        bitrate="8M",
        camera_controls=None,
    ):
        self._device = device
        self._recordings_dir = recordings_dir
        self._width = width
        self._height = height
        self._segment_seconds = segment_seconds
        self._bitrate = bitrate
        self._camera_controls = camera_controls or {}
        self._proc = None
        self._splitter = JpegFrameSplitter()
        self._pending = collections.deque()

    def open(self):
        os.makedirs(self._recordings_dir, exist_ok=True)
        _set_camera_controls(self._device, self._camera_controls)
        cmd = [
            "ffmpeg",
            "-f", "v4l2",
            "-input_format", "mjpeg",
            "-video_size", f"{self._width}x{self._height}",
            "-i", self._device,
            "-map", "0:v",
            "-c:v", "h264_v4l2m2m",
            "-b:v", self._bitrate,
            "-pix_fmt", "yuv420p",
            "-f", "segment",
            "-segment_time", str(self._segment_seconds),
            "-reset_timestamps", "1",
            "-strftime", "1",
            # See camera/camera_service.py's history for why fragmented MP4
            # (without empty_moov) is required here: it keeps a segment
            # interrupted mid-write playable, and empty_moov breaks the Pi's
            # hardware encoder (its SPS/PPS extradata isn't available until
            # the first encoded frame comes back).
            "-segment_format", "mp4",
            "-segment_format_options", "movflags=+frag_keyframe+default_base_moof",
            os.path.join(self._recordings_dir, "Camera_%Y-%m-%d_%H-%M-%S.mp4"),
            "-map", "0:v",
            "-c:v", "copy",
            "-f", "mjpeg",
            "-",
        ]
        log.info("Starting ffmpeg (recording + detection feed)")
        self._proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self._splitter = JpegFrameSplitter()
        self._pending = collections.deque()

    def read(self):
        if self._proc is None:
            return False, None
        while True:
            while self._pending:
                jpg = self._pending.popleft()
                frame = cv2.imdecode(np.frombuffer(jpg, dtype=np.uint8), cv2.IMREAD_COLOR)
                if frame is not None:
                    return True, frame
            chunk = self._proc.stdout.read(4096)
            if not chunk:
                return False, None
            self._pending.extend(self._splitter.feed(chunk))

    def release(self):
        if self._proc is None:
            return
        self._proc.terminate()
        try:
            self._proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self._proc.kill()
        self._proc = None
