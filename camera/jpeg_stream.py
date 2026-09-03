"""Shared MJPEG byte-stream parsing: splits arbitrary-sized reads into
individual JPEG frames by locating SOI (0xffd8)/EOI (0xffd9) markers. Used by
camera/capture.py, camera/ffmpeg_capture.py, and streaming/live_stream.py,
which otherwise each reimplemented this buffering independently."""


class JpegFrameSplitter:
    def __init__(self):
        self._buffer = b""

    def feed(self, chunk: bytes) -> list:
        """Append `chunk` and return any complete JPEG frames (raw bytes,
        SOI..EOI inclusive) now available in the buffer."""
        self._buffer += chunk
        frames = []
        while True:
            start = self._buffer.find(b"\xff\xd8")
            end = self._buffer.find(b"\xff\xd9", start + 2) if start != -1 else -1
            if start == -1 or end == -1:
                break
            frames.append(self._buffer[start : end + 2])
            self._buffer = self._buffer[end + 2 :]
        return frames
