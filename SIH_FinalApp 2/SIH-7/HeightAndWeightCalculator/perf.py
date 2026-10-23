"""
Performance helpers shared by all exercise modules.

Why the laptop froze before:
  * every module ran its video loop as fast as the CPU allowed (no FPS cap)
  * OpenCV / PyTorch each grabbed every CPU core
  * cameras were never released when the browser tab closed
  * heavy models were loaded at import time, and twice because of Flask's debug reloader

Tune with environment variables (all optional):
  DEEPFIT_THREADS      CPU threads for OpenCV/PyTorch          (default 2)
  DEEPFIT_STREAM_FPS   max frames per second sent to browser   (default 15)
  DEEPFIT_JPEG_QUALITY JPEG quality of the video stream        (default 70)
  DEEPFIT_POSE_COMPLEXITY  MediaPipe pose model 0/1/2          (default 1)
"""

import os
import sys
import time

import cv2

THREADS = int(os.environ.get("DEEPFIT_THREADS", "2"))
STREAM_FPS = float(os.environ.get("DEEPFIT_STREAM_FPS", "15"))
JPEG_QUALITY = int(os.environ.get("DEEPFIT_JPEG_QUALITY", "70"))
POSE_COMPLEXITY = int(os.environ.get("DEEPFIT_POSE_COMPLEXITY", "1"))


def limit_threads() -> None:
    """Stop OpenCV / PyTorch from using every core (keeps the Mac responsive)."""
    try:
        cv2.setNumThreads(THREADS)
    except Exception:
        pass
    if "torch" in sys.modules:
        try:
            sys.modules["torch"].set_num_threads(THREADS)
        except Exception:
            pass


def open_camera(width: int = 640, height: int = 480, fps: int = 30):
    """Open the default webcam with a small buffer so frames are never stale."""
    cam = None
    if sys.platform == "darwin":
        cam = cv2.VideoCapture(0, cv2.CAP_AVFOUNDATION)
    if cam is None or not cam.isOpened():
        cam = cv2.VideoCapture(0)
    if cam.isOpened():
        cam.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        cam.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        cam.set(cv2.CAP_PROP_FPS, fps)
        try:
            cam.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass
    return cam


def release_camera(cam) -> None:
    try:
        if cam is not None:
            cam.release()
    except Exception:
        pass


class FrameThrottle:
    """Sleep just enough to keep a loop at <= max_fps (frees CPU for everything else)."""

    def __init__(self, max_fps: float = STREAM_FPS):
        self.min_interval = 1.0 / max_fps if max_fps > 0 else 0.0
        self._last = 0.0

    def wait(self) -> None:
        if self.min_interval <= 0:
            return
        now = time.time()
        sleep_for = self.min_interval - (now - self._last)
        if sleep_for > 0:
            time.sleep(sleep_for)
        self._last = time.time()


def encode_jpeg(frame) -> bytes:
    ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY])
    return buf.tobytes() if ok else b""


def mjpeg_chunk(jpeg: bytes) -> bytes:
    return b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"


limit_threads()
