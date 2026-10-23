# DeepFit innovations

Most SIH25073 solutions measure what a child can do today. DeepFit adds five features
on top of that: it measures how fast the child learns, adjusts for physical maturity,
makes results verifiable, guides blind athletes by sound, and lets a phone app work offline
while the server re-checks every result.

## 1. Coachability Challenge (`coachability.py`, test key `coachability`)

**What it does**

- A random 5-move pattern is generated for each attempt (code like `#L88DF`). The moves come
  from 11 that the camera recognises reliably: hands up, one hand up, hands on head, arms out,
  hands on hips, squat, touch knees, step left, step right, and jump.
- Each try has three stages:
  1. **Preview.** The pattern is shown and spoken.
  2. **Go.** The athlete performs it while the camera recognises each move (held about 1/3 s).
  3. **Score and tip.** The try is scored and one tip is given about its biggest mistake.
- **Errors per try** come from the edit distance between the pattern and what was done
  (each wrong, missed or extra move = 1 error). A move started more than 2.5 s after the
  previous one adds 0.5 error.
- **Score (0–100):** 65% × how much errors fall from try 1 to the average of tries 4–5,
  plus 35% × accuracy at the end. If try 1 is already perfect, learning can't be measured, so
  the score is capped at 90 with a note.
- **Percentile:** uses a STARTER norm (mean 45, sd 20) until real data exists.

## 2. Growth Measures + Hidden Potential Index (`growth.py`, `potential.py`)

**Growth Measures**

- **What the athlete enters:** standing height and weight (measured with a tape and a scale),
  plus the chair height.
- **What the camera measures:** sitting height, as a ratio against standing height with the
  camera fixed in place. Eye height ≈ 93.6% of standing height.
- **Maturity estimate:** the Mirwald (2002) maturity-offset equation gives years before or
  after peak height velocity (PHV).
  - It compares that against the average age at PHV: 13.8 for boys and 11.8 for girls. Change
    these with `DEEPFIT_MEAN_APHV_M` / `_F`.
  - Result: **early**, **on time** or **late** developer, using a ±1 year boundary.
- **Limits:** the equation was developed on European-ancestry samples and is most reliable
  for ages 8–16. Read the result as roughly ±1 year.

**Hidden Potential Index (0–100)**

- **Formula:** 30% × maturity-adjusted fitness + 40% × coachability + 30% × growth headroom.
- **Maturity-adjusted fitness:** test results are re-rated against targets for the athlete's
  *biological* age (age − years behind average).
- **Growth headroom:** 50 + 25 × years later than average, clamped to 0–100.
- **Late bloomer flag:** set when growth is at least 1 year behind average, adjusted fitness
  is at least 50 and coachability is at least 60.
- **Report** (`/potential`): shows the three signals plus a rank among athletes from the same
  place, by today's fitness and by potential.

## 3. Talent Passport (`passport.py`)

- **What is signed:** every camera test saves a **skeleton-only replay** (33 body points at
  10 fps; no image and no face). The result, the identity evidence (the pre-test face match
  score, plus live re-checks passed out of those run) and the hash of the replay are signed
  with HMAC-SHA256.
- **Result page:** `/passport/r/<id>/<token>` is public but unguessable. It shows VERIFIED or
  NOT VALID (with the reason), the identity evidence, a replay player and a QR code.
- **Athlete page:** `/passport/a/<token>` lists all of the athlete's signed results.
- **Tampering:** editing a score in the database, or swapping the replay, makes the page show
  NOT VALID.
- **Secret:** set `PASSPORT_SECRET` in `.env` once and keep it. Changing it makes every old
  passport show NOT VALID.

## 4. Audio mirror (blind mode)

- **What it does:** a continuous tone whose pitch rises as the body gets closer to the correct
  position. It's on by default in blind mode, and **M** toggles it.
- **When it's correct:** at 95% or higher it becomes a steady, gently pulsing high tone.
- **Speech:** the tone quiets automatically while the app is speaking.
- **Visual version:** the same signal drives the on-screen **Form meter** for everyone.
- **Where it's defined:** each exercise's `mirror()` method in `exercise_engine.py`.

## 5. Phone app with server re-check (`mobile_api.py`, `deepfit_mobile/`)

- **What it does:** the Flutter app runs every test on the phone with no internet needed
  (Google ML Kit body tracking, same 33 points as MediaPipe, and a Dart copy of the engine).
- **Why a modified app can't cheat:** the phone uploads the skeleton track and face
  snapshots, not just the score. The server checks every snapshot against the registration
  photo, then re-runs the Python engine on the skeleton and saves *its own* number. The
  Talent Passport notes "captured on the DeepFit phone app - score recomputed by the server".
- **Same numbers on both sides:** `deepfit_mobile/test/engine_parity_test.dart` replays 30
  recorded movements through the Dart engine and compares them with the Python results.

## What is NOT proven yet

- The predictive value of the Coachability score and of the Hidden Potential Index needs a pilot:
  - **Test-retest consistency:** the same kids should get similar scores two days apart.
  - **Agreement with PE-teacher ratings.**
  - **Fairness checks:** scores shouldn't simply track age, gender or phone familiarity.
- Every threshold, weight and norm here is a starter value meant to be tuned with that data.
