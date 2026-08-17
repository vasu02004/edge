import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2

BOUNDARY = "frame"


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        if self.path != "/" and self.path != "/stream":
            self.send_response(404)
            self.end_headers()
            return

        self.send_response(200)
        self.send_header("Age", "0")
        self.send_header("Cache-Control", "no-cache, private")
        self.send_header("Pragma", "no-cache")
        self.send_header(
            "Content-Type", f"multipart/x-mixed-replace; boundary={BOUNDARY}"
        )
        self.end_headers()

        streamer = self.server.streamer
        last_frame_id = 0
        try:
            while True:
                jpeg, last_frame_id = streamer.wait_for_frame(last_frame_id)
                if jpeg is None:
                    break
                self.wfile.write(f"--{BOUNDARY}\r\n".encode())
                self.wfile.write(b"Content-Type: image/jpeg\r\n")
                self.wfile.write(f"Content-Length: {len(jpeg)}\r\n\r\n".encode())
                self.wfile.write(jpeg)
                self.wfile.write(b"\r\n")
        except (BrokenPipeError, ConnectionResetError):
            pass


class MJPEGStreamer:
    def __init__(self, host="0.0.0.0", port=8080, jpeg_quality=80):
        self._jpeg_quality = jpeg_quality
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
        self._latest_jpeg = None
        self._frame_id = 0
        self._stopped = False

        self._server = ThreadingHTTPServer((host, port), _Handler)
        self._server.streamer = self
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._host = host
        self._port = port

    def start(self):
        self._thread.start()
        print(f"MJPEG stream available at http://<pi-ip>:{self._port}/stream")

    def update_frame(self, frame):
        ok, buf = cv2.imencode(
            ".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), self._jpeg_quality]
        )
        if not ok:
            return
        with self._condition:
            self._latest_jpeg = buf.tobytes()
            self._frame_id += 1
            self._condition.notify_all()

    def wait_for_frame(self, last_frame_id, timeout=5.0):
        with self._condition:
            while not self._stopped and (
                self._latest_jpeg is None or self._frame_id == last_frame_id
            ):
                self._condition.wait(timeout=timeout)
            if self._stopped:
                return None, last_frame_id
            return self._latest_jpeg, self._frame_id

    def stop(self):
        with self._condition:
            self._stopped = True
            self._condition.notify_all()
        self._server.shutdown()
