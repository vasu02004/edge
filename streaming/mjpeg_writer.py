"""Shared MJPEG multipart HTTP response helpers, used by both the live
detection stream (streaming/mjpeg_server.py) and the standalone raw-camera
live view (streaming/live_stream.py), which otherwise duplicated this
byte-for-byte."""


def start_mjpeg_response(handler, boundary="frame"):
    handler.send_response(200)
    handler.send_header("Age", "0")
    handler.send_header("Cache-Control", "no-cache, private")
    handler.send_header("Pragma", "no-cache")
    handler.send_header("Content-Type", f"multipart/x-mixed-replace; boundary={boundary}")
    handler.end_headers()


def write_mjpeg_frame(wfile, jpeg_bytes, boundary="frame"):
    wfile.write(f"--{boundary}\r\n".encode())
    wfile.write(b"Content-Type: image/jpeg\r\n")
    wfile.write(f"Content-Length: {len(jpeg_bytes)}\r\n\r\n".encode())
    wfile.write(jpeg_bytes)
    wfile.write(b"\r\n")
