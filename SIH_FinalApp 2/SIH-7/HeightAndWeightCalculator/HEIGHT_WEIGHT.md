# Height & Weight – a built-in camera test

Height & Weight used to be a separate Python program. The website started it as a subprocess, and it needed PyTorch and the old MediaPipe API, so it broke on newer Python versions. It is now a normal DeepFit test at `/ex/height_weight`, like push-ups or the plank: the same page, the same face check, the same Talent Passport, and the same phone app flow.

## Works on every Python / MediaPipe version

`pose_backend.py` uses whichever MediaPipe is installed:

- **Old MediaPipe** (`mp.solutions.pose`): used as before.
- **New MediaPipe** (the only kind for the newest Python versions, Tasks API): `PoseLandmarker`. Its small model file is downloaded once into `models/`, so the first start needs internet.

Both give the same 33 points and the person outline. **All camera tests** now start through it, not only height.

The three oldest test pages (sit-ups, vertical jump, dumbbell) still use the old API. If they can't load, the site still starts, and their addresses open the same test in the shared engine.

No PyTorch, no subprocess.

## How height is measured

**Setup (once per wall):**

- Print `/height/marker` at 100 %. It has two sheets with a 16 cm code each.
- **FLOOR sheet:** cut on the dashed line, stand it on the floor against the wall.
- **TOP sheet:** tape it anywhere above the head. No measuring is needed.
- **No printer?** Use two plain A4 sheets on a darker wall instead.

**Why on the floor.** The floor sheet's bottom edge *is* the floor line, exactly where the heels stand, so the feet never need to be found. Measuring to the toes would be several cm wrong: they stick out about 25 cm towards the camera and look lower than the floor.

**Why two sheets.** One sheet cannot tell how much the camera is tilted, and a 2° tilt adds about 4 cm. With both sheets, the mapping from picture to wall (in cm) is pinned at both ends of the body:

- A homography is fitted to their 8 corners.
- The top sheet's position is solved for.
- So a tilted, turned or off-centre camera is handled exactly.

**Corners to about 1/20 pixel.** Each sheet edge is located at dozens of points, a straight line is fitted through them, and the lines are intersected.

**Head top.** It comes from the MediaPipe person outline, at the sub-pixel point where the mask crosses 50 %.

**Parallax.** The top of the head is about 8 cm in front of the wall, and a round head's outline is slightly above the crown. The camera position, worked out from the same corners, corrects both.

**When it finishes.** The test ends by itself when 25 frames agree within ±0.5 cm.

**Problems it reports instead of guessing:**

- a sheet is missing;
- the floor sheet is not on the floor;
- the sheets don't match (mis-printed or bent);
- knees are bent;
- head or feet are out of view;
- there is no outline.

## How weight is measured

A camera cannot weigh anyone. **📷 Read my scale** photographs the scale display, and a vision model reads the number (Muse Spark, or Qwen vision on Groq).

- Pounds and stone are converted.
- Values that are not a body weight are rejected.
- An unsure reading is flagged for checking.

The weight is therefore as accurate as the scale (usually ±0.1 kg). It can also be typed. BMI uses WHO adult categories; under 18, a BMI-for-age note is shown instead.

## Accuracy – the honest numbers

**In 40 rendered 3D scenes, the geometry is correct to within 0.5 cm.** The scenes used:

- a pinhole camera at 2–3.8 m;
- tilt of ±11° and turn of ±10°;
- the DeepFit sheets and plain A4 sheets;
- heights from 118 to 188 cm;
- image noise and soft edges.

The mean error was 0.07 cm. The scenes were also checked with:

- the camera's focal length 15 % off;
- a portrait phone;
- a mirrored front-camera picture.

**Expected in real use: about ±1 cm (≈ 99.4 % for 165 cm).** What adds the rest:

- how well the outline follows the hair: up to ±0.5 cm;
- posture;
- lens distortion of wide webcams: up to about 1 cm, so keep the athlete in the middle of the picture;
- **print scale: printing at 97 % makes everyone about 5 cm shorter.** Check the 10 cm line on the sheet.

**99.99 % is not possible for anyone.** That would be ±0.02 cm. A school stadiometer gives ±0.1–0.5 cm, and a person is about 1 cm shorter in the evening than in the morning.

## Where it is saved

The result goes to `exercise_results` with a Talent Passport. It also goes to `Final_Estimated_Height_and_Weight` with the old fields, so the dashboard, reports and qualification keep working.

The saved result includes:

- the samples and their spread;
- which sheets were seen;
- the fit error;
- the camera distance and height;
- where the weight came from.

## Phone app

The Height & Weight screen has:

- **Measure with the camera:** set-up help and a link to print the sheets, then a 10 s spoken self-timer and 3 sharp photos → `POST /api/v1/height_weight/measure`. The same maths runs on the server.
- **Read my scale (photo):** `POST /api/v1/vision/scale`.

Typing still works offline through the outbox. Camera-measured heights are also written for the dashboard.

## Files

- `stature.py`: sheets, wall mapping, head top, parallax, the engine test, phone photos and the printable codes.
- `pose_backend.py`: MediaPipe on any version.
- `vision_reader.py`: scale display and dumbbell number.
- `templates/height_marker.html`: the printable sheets.

## Tests

- `test_stature.py` (27 checks + the 40-scene sweep): rendered 3D scenes, problems, the engine loop, BMI, phone photos and the mirrored picture.
- `test_height_routes.py` (38 checks):
  - new MediaPipe Tasks code path (real 0.10.32, fake model);
  - pages and redirects;
  - the printable sheets (also measured in a PDF: code exactly 16.00 cm, cut line exactly 3.00 cm below);
  - scale and dumbbell reading;
  - a whole camera height test through Flask, saved where the dashboard reads it;
  - the phone endpoints.

**Not tested here:**

- a real webcam and a real person;
- the MediaPipe model download, which this sandbox blocks;
- live Groq/Meta calls, which were mocked.
