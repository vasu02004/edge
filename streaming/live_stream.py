#!/usr/bin/env python3
"""MJPEG live-view server for the webcam. View at http://<pi-ip>:8090/ in
any browser, or forward the port with ngrok for remote access.

Uses only the standard library + ffmpeg (already required by main.py's
recording pipeline, see camera/ffmpeg_capture.py), so nothing extra needs
installing.

NOTE: /dev/video0 can only be opened by one process at a time. Stop the
tracker service (which owns the camera for both detection and recording)
before running this:
    sudo systemctl stop edge-tracker.service

Usage:
    python3 streaming/live_stream.py
    ngrok http 8090
"""
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DEVICE = "/dev/video0"
WIDTH, HEIGHT = 1920, 1080
PORT = 8090
BOUNDARY = "frame"

INDEX_HTML = b"""<!doctype html>
<html><body style="margin:0;background:#000">
<img src="/stream" style="width:100%;height:100vh;object-fit:contain">
</body></html>"""


def read_jpeg_frames(proc):
    buf = b""
    while True:
        chunk = proc.stdout.read(4096)
        if not chunk:
            return
        buf += chunk
        start = buf.find(b"\xff\xd8")
        end = buf.find(b"\xff\xd9")
        if start != -1 and end != -1 and end > start:
            yield buf[start:end + 2]
            buf = buf[end + 2:]


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(INDEX_HTML)
            return

        if self.path != "/stream":
            self.send_response(404)
            self.end_headers()
            return

        self.send_response(200)
        self.send_header("Age", "0")
        self.send_header("Cache-Control", "no-cache, private")
        self.send_header("Pragma", "no-cache")
        self.send_header("Content-Type", f"multipart/x-mixed-replace; boundary={BOUNDARY}")
        self.end_headers()

        proc = subprocess.Popen(
            [
                "ffmpeg",
                "-f", "v4l2",
                "-input_format", "mjpeg",
                "-video_size", f"{WIDTH}x{HEIGHT}",
                "-i", DEVICE,
                "-f", "mjpeg",
                "-q:v", "5",
                "-",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        try:
            for frame in read_jpeg_frames(proc):
                self.wfile.write(f"--{BOUNDARY}\r\n".encode())
                self.wfile.write(b"Content-Type: image/jpeg\r\n")
                self.wfile.write(f"Content-Length: {len(frame)}\r\n\r\n".encode())
                self.wfile.write(frame)
                self.wfile.write(b"\r\n")
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()

    def log_message(self, format, *args):
        pass


def main():
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"Live view at http://0.0.0.0:{PORT}/")
    server.serve_forever()


if __name__ == "__main__":
    main()
