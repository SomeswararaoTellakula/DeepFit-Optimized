"""
Download the two small face models used by identity_guard.py.

    python download_face_models.py

They are already included in models/face/, so you only need this if that
folder was deleted (for example on a fresh clone without the model files).
"""

import hashlib
import os
import urllib.request

BASE = "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/"
MODELS = {
    "face_detection_yunet_2023mar.onnx": (
        BASE + "face_detection_yunet/face_detection_yunet_2023mar.onnx",
        "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",
    ),
    "face_recognition_sface_2021dec.onnx": (
        BASE + "face_recognition_sface/face_recognition_sface_2021dec.onnx",
        "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79",
    ),
}

target_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models", "face")
os.makedirs(target_dir, exist_ok=True)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


for name, (url, expected) in MODELS.items():
    path = os.path.join(target_dir, name)
    if os.path.exists(path) and sha256(path) == expected:
        print(f"OK   {name}")
        continue
    print(f"GET  {name} ...")
    urllib.request.urlretrieve(url, path)
    if sha256(path) != expected:
        os.remove(path)
        raise SystemExit(f"Checksum mismatch for {name}; download again.")
    print(f"OK   {name}")

print("Face models ready in", target_dir)
