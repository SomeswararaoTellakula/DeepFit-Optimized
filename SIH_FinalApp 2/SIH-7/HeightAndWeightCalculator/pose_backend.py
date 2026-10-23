"""
Body tracking that works with every MediaPipe version.

MediaPipe up to ~0.10.14 offers `mp.solutions.pose`. Newer releases (the only ones for the newest
Python versions) removed it and only have the Tasks API (`PoseLandmarker` + a .task model file).
DeepFit used `mp.solutions` everywhere, so on a new Python the camera tests could not start.

PoseBackend picks whichever is installed:
    legacy  -> mp.solutions.pose.Pose
    tasks   -> mediapipe.tasks PoseLandmarker; the model file is downloaded once into models/
Both return the same thing: an object with `.landmark` (33 points with x, y, z, visibility, all
normalised 0..1) and, if asked, a person mask (float32 H x W, 1 = person).
"""

import os
import threading
import time
import urllib.request
from types import SimpleNamespace
from typing import Optional, Tuple

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL_DIR = os.path.join(HERE, "models")
MODEL_URL = "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_{v}/float16/1/pose_landmarker_{v}.task"
VARIANT = {0: "lite", 1: "full", 2: "heavy"}
CONNECTIONS = [(11, 12), (11, 13), (13, 15), (12, 14), (14, 16), (11, 23), (12, 24), (23, 24), (23, 25), (25, 27),
               (24, 26), (26, 28), (27, 29), (29, 31), (27, 31), (28, 30), (30, 32), (28, 32), (15, 19), (16, 20)]
_dl_lock = threading.Lock()


def has_legacy() -> bool:
    try:
        import mediapipe as mp
        return hasattr(mp, "solutions") and hasattr(mp.solutions, "pose")
    except Exception:
        return False


def model_path(complexity: int = 1) -> str:
    """The Tasks model file, downloaded on first use (needs internet once)."""
    v = VARIANT.get(int(complexity), "full")
    path = os.path.join(MODEL_DIR, f"pose_landmarker_{v}.task")
    with _dl_lock:
        if not os.path.exists(path) or os.path.getsize(path) < 1_000_000:
            os.makedirs(MODEL_DIR, exist_ok=True)
            tmp = path + ".part"
            urllib.request.urlretrieve(MODEL_URL.format(v=v), tmp)
            os.replace(tmp, path)
    return path


class PoseBackend:
    """process(bgr_frame, t_seconds) -> (landmarks or None, mask or None)."""

    def __init__(self, segmentation: bool = False, complexity: int = 1, still_images: bool = False):
        self.segmentation = segmentation
        self.still = still_images
        self._last_ms = -1
        if has_legacy():
            import mediapipe as mp
            self.kind = "legacy"
            self._p = mp.solutions.pose.Pose(static_image_mode=still_images, model_complexity=int(complexity),
                                             enable_segmentation=segmentation,
                                             min_detection_confidence=0.5, min_tracking_confidence=0.5)
        else:
            import mediapipe as mp
            from mediapipe.tasks import python as mp_tasks
            from mediapipe.tasks.python import vision
            self.kind = "tasks"
            self._mp = mp
            opts = vision.PoseLandmarkerOptions(
                base_options=mp_tasks.BaseOptions(model_asset_path=model_path(complexity)),
                running_mode=vision.RunningMode.IMAGE if still_images else vision.RunningMode.VIDEO,
                num_poses=1, output_segmentation_masks=segmentation,
                min_pose_detection_confidence=0.5, min_pose_presence_confidence=0.5, min_tracking_confidence=0.5)
            self._p = vision.PoseLandmarker.create_from_options(opts)

    def process(self, bgr, t: Optional[float] = None) -> Tuple[Optional[SimpleNamespace], Optional[np.ndarray]]:
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        if self.kind == "legacy":
            r = self._p.process(rgb)
            mask = r.segmentation_mask if self.segmentation and getattr(r, "segmentation_mask", None) is not None else None
            return r.pose_landmarks, (np.array(mask, dtype=np.float32) if mask is not None else None)
        img = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb))
        if self.still:
            r = self._p.detect(img)
        else:
            ms = int((t if t is not None else time.time()) * 1000)
            ms = max(ms, self._last_ms + 1)            # the video mode needs increasing timestamps
            self._last_ms = ms
            r = self._p.detect_for_video(img, ms)
        if not r.pose_landmarks:
            return None, None
        lms = SimpleNamespace(landmark=[SimpleNamespace(x=p.x, y=p.y, z=p.z,
                                                        visibility=p.visibility if p.visibility is not None else 1.0)
                                        for p in r.pose_landmarks[0]])
        mask = None
        if self.segmentation and getattr(r, "segmentation_masks", None):
            mask = np.array(r.segmentation_masks[0].numpy_view(), dtype=np.float32).reshape(bgr.shape[0], bgr.shape[1])
        return lms, mask

    def close(self):
        try:
            self._p.close()
        except Exception:
            pass


def draw(frame, landmarks, color=(245, 200, 66)) -> None:
    """Skeleton overlay with plain OpenCV (no MediaPipe drawing helpers needed)."""
    if landmarks is None:
        return
    h, w = frame.shape[:2]
    pts = [(int(p.x * w), int(p.y * h), getattr(p, "visibility", 1.0)) for p in landmarks.landmark]
    for a, b in CONNECTIONS:
        if a < len(pts) and b < len(pts) and pts[a][2] > 0.5 and pts[b][2] > 0.5:
            cv2.line(frame, pts[a][:2], pts[b][:2], color, 2, cv2.LINE_AA)
    for x, y, v in pts[11:]:
        if v > 0.5:
            cv2.circle(frame, (x, y), 3, (255, 255, 255), -1, cv2.LINE_AA)
