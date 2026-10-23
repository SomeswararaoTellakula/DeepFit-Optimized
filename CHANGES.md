# DeepFit – optimisation & identity-check update

## 1. Only the registered athlete can do an exercise

**Before:** the face check compared four distances between the eyes, nose and chin.
Almost any face passed. DeepFace was meant to be used, but it isn't in
`requirements.txt`, so the weak check always ran. The check also lived only
in the browser, so calling `/situp/start_camera` directly skipped it.
Sit-ups had no server-side check, and the dumbbell check crashed on the first mismatch.

**Now** (`identity_guard.py`):

| Step | What happens |
|---|---|
| Registration | The photo must contain **exactly one clear face**, or signup is rejected with a message. |
| Before an exercise | The athlete clicks *Verify Identity*. The live face is compared with the registration photo using **OpenCV YuNet + SFace** face recognition (about 20 ms on the CPU). |
| Server gate | `/situp`, `/dumbbell`, `/vertical_jump` and `/height` `start_camera` refuse to start (HTTP 403) unless the same user passed the face check in the last 5 minutes. |
| During the exercise | Every 2 s, in a background thread, the server compares the face on camera with the registration photo. After 3 mismatches in a row the exercise stops and the page shows the alert. A turned-away face does not count as a mismatch. A badge on the video shows *ID verified* or *ID MISMATCH*. |
| Multiple people | The pre-exercise check fails if more than one face is in view. |

The test results below come from a sample photo, not a real webcam:

| Case | Similarity | Result |
|---|---|---|
| Same person (mirrored, darker, smaller, rotated) | 0.90 – 0.98 | ✅ accepted |
| Different people | 0.04 – 0.21 | ❌ rejected |
| Threshold | 0.40 | |

## 2. The laptop no longer freezes

| Cause | Fix |
|---|---|
| Height page ran **MiDaS DPT_Large on every frame** (1–3 s per frame on the CPU), but its depth output was never used | Off by default (`DEEPFIT_ENABLE_DEPTH=1` turns on the small model) |
| MediaPipe Holistic / Pose at `model_complexity=2`, plus a segmentation mask and face mesh that were never used | Complexity 1, unused outputs off |
| Video loops ran as fast as possible | Capped at 15 fps (24 fps for vertical jump), JPEG quality 70 |
| OpenCV / PyTorch used every CPU core | Limited to 2 threads (`DEEPFIT_THREADS`) |
| `debug=True` started a second process that loaded every model twice | Reloader off (`FLASK_DEBUG=1` for development) |
| 5 separate face verifiers, each with a FaceMesh model | 1 shared engine |
| Models loaded at import (jump detector, PyTorch) | Loaded on first use |
| Webcam not released when a stream ended; a dumbbell Pose graph leaked on every start | Released and closed in `finally` blocks |
| Every `get_stats` poll was written to the log file (6.6 MB of logs) | Polling endpoints aren't logged |

## 3. Security
* Gemini API keys removed from all code and docs. **Revoke the old keys** in Google AI Studio.
  Put the new key in `.env` (see `.env.example`).
* `requirements.txt` cleaned up: only one OpenCV build, `python-dotenv` added, unused packages
  (ultralytics, transformers, matplotlib, seaborn) removed.

## Run on macOS
```bash
cd "SIH_FinalApp 2/SIH-7/HeightAndWeightCalculator"
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r ../../../requirements.txt
cp .env.example .env          # then fill in GEMINI_API_KEY
python app.py                 # http://localhost:7860
```
The `venv/` and `venv39/` folders in the original project are **Windows** environments
(they contain `Scripts/` and `.whl` files for win_amd64). They can't run on a Mac and use about 4 GB.

## Known issue (not changed)
`integrated_system.py` doesn't measure height and weight yet. `estimate_height_enhanced`
returns `175 + random noise`, and the weight is a random BMI × height². This must be
replaced with a real estimate before a demo.
