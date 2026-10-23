# Weighted dumbbell curls

The curl test used to count reps only. It now takes the dumbbell weight into account: every rep is measured, and the benchmark depends on the weight that was lifted.

## What the research suggestion gets right, and what it doesn't

**Helpful:**

- **Object detection can find the dumbbell.** YOLO-style detectors (or SAM 3.1 with the prompt "dumbbell") put a box around it.
- **The bar path can be tracked.** A detector's box can be followed across frames. In a curl the dumbbell sits in the hand, so the wrist point that pose tracking already gives us *is* the bar path. No extra model is needed for tracking.

**Not possible from the video of the set:**

- **Reading the kilograms during the set.** From 2 m away, with the dumbbell moving, the "5 KG" on the end cap is a few blurred pixels. A close-up photo before the set is different: there the number is readable (see step 1).
- **Using size as a proxy.** An adjustable dumbbell is as long at 2.5 kg as at 10 kg, and a water bottle can stand in for a light one.
- **Using angles as a proxy.** The body angles depend on how heavy the weight is *for that person*: a strong adult curls 10 kg with the same upright form a child shows with 2 kg. So "5 kg gives this angle, 10 kg gives that angle" is not true across people.

**What DeepFit does instead** (the approach used by velocity-based-training devices):

1. **The system detects the weight.** The athlete presses **📷 Detect my dumbbell** and holds the dumbbell up to the camera with the number facing it. A vision model (Muse Spark, or the Groq fallback - see `llm.py`) reads what is printed or moulded on it ("5 KG", "10 LB" → 4.54 kg) - `vision_reader.read_dumbbell`.
   - Number read → the weight is set, marked *read off the dumbbell*.
   - No number visible → it estimates from the type and size next to the hand (a water bottle = 1 kg) and asks the athlete to confirm; the result says *estimated, confirmed by you*.
   - No AI key / no connection, or the athlete prefers → pick it: No weight/bottle, 1, 2, 3, 5, 7.5, 10 kg, or any other value (*picked by you*).
   - How the weight was found is saved with the result (`load_detect`). If the weight is changed after detection, it is recorded as picked.
2. **SAM 3.1 checks the hand.** During the test, the server sends one frame to SAM 3.1 with the prompt "dumbbell". It records whether a dumbbell box sits within about one forearm-length of a wrist ("seen"), and its length in cm.
3. **The camera measures how that weight moved, for every rep:**
   - **Elbow angle at the top:** how far the arm bent.
   - **Lifting speed:** wrist travel in cm ÷ lift time = m/s. Pixels become cm using forearm length ≈ 0.146 × height.
   - **Body swing:** shoulder movement, as % of shoulder width. Over 15% = cheating.
   - **Elbow drift:** the elbow rising forward, as % of upper-arm length. Over 25% = cheating.
   - **Clean rep:** neither limit was broken.
4. **From weight + reps + speed it works out:**
   - **One-rep max (1RM).** If the set slowed down a lot (≥ 20% speed loss) it was near failure, so the Brzycki/Epley formula from clean reps is reliable. Otherwise the load-velocity line estimates it from the first reps' speed. If the weight was too light for either, the reps formula gives a lower limit.
   - **How heavy it was for you:** light, moderate or heavy.
   - **The weight to try next time.**
5. **Benchmark for that weight.** `curl_load_benchmarks.csv` has one row per population × gender × age band × dumbbell weight. Each row gives:
   - target clean reps in 60 s;
   - expected lifting speed at that weight;
   - expected elbow angle at the top at that weight;
   - the swing and drift limits;
   - a reference 1RM.

   Heavier dumbbell → fewer target reps, slower expected speed, less elbow bend: different weights, different benchmarks. Lifting more than the reference maximum for the group is rated Excellent.
6. **The internal benchmarks check the weight** (`curl_load.weight_check`). The speed of the first reps says how heavy the dumbbell was *for this athlete* (% of their max, from the load-velocity line). Weight ÷ that % = the 1-rep max they would need.
   - If that is more than 4 × the reference 1RM for their age group, or more than 60 % of their body weight (beyond elite one-arm curls): **"It moved like a lighter weight - check the number on the dumbbell"**, with the weight it moved like.
   - If it is less than 0.35 × the reference: **"It moved like a heavier weight"** (or the lift was slowed on purpose).
   - Otherwise: "The speed fits a 5 kg dumbbell: it was about 60 % of your max."

   Example: a 12-year-old "curling 5 kg" at 1.6 m/s is flagged (moves like ≈ 0.5 kg); the same boy at 0.6 m/s fits. Needs at least 3 reps. The limits are starter values like the rest of the table.

**All constants are starter values.** `export_curl_dataset.py` writes the real dataset (one row per rep, athletes pseudonymous) so they can be replaced with values learned from field testing. An athlete who tests at two weights gives their own load-velocity line, the standard way to measure strength without a maximal lift.

## Where it shows

**Website (`/ex/dumbbell_curls`):**

- **📷 Detect my dumbbell** first (photo from the webcam, or upload one), the weight picker as the fallback.
- Live chips showing the last rep's speed, elbow angle and clean / swing.
- The result says "14 reps × 5 kg", the target for that weight, a table (clean reps, speed first → last, elbow angle vs expected, swing/drift vs limits, 1RM, next weight, how the weight was found, **weight vs benchmark**, dumbbell in the hand) and a bar chart of each rep's speed (green = clean).

**Phone app:**

- **Detect my dumbbell** (front camera photo → `/api/v1/dumbbell/detect`), and the same weight picker.
- The weight and how it was found are sent with the upload.
- The server re-runs the test with it.
- The result screen shows the same analysis, including the weight check.

**Talent Passport:**

- Shows "10 reps × 5 kg" and the weighted-curl panel.
- **The weight is part of the signature**, so changing it later makes the passport NOT VALID. Older results without a weight still verify.

**Counting is unchanged:** same thresholds, same feedback and events. The phone app's on-device engine still matches the server: all 30 parity cases were regenerated and are identical.

## Tested here

`test_curl_load.py` has 43 checks; `test_height_routes.py` covers the detect endpoints:

- Speed, angle, swing and drift are measured.
- Swinging or drifting reps are not clean.
- Fatigue is detected and the right 1RM formula is chosen.
- The benchmark table ordering, and lifting above the max rated Excellent.
- The SAM box near/far from the hand (mocked).
- The signed weight.
- Phone upload → server re-run → 5 kg benchmark → passport page.
- Impossible weights ignored, the curl page picker, and the dataset export.
- Detection: "10 LB" read → 4.54 kg; no number → estimate to confirm; water bottle → 1 kg; nothing held up; AI unreachable; the detected weight travels with the set and is dropped if changed.
- The weight check: lighter / heavier / fits / body-weight limit / too few reps.

**Not tested here:** a real camera with a real dumbbell, and the live vision and SAM 3.1 calls (mocked; this sandbox cannot reach Groq or Meta).
