# Weighted dumbbell curls

The curl test used to count reps only. It now takes the dumbbell weight into account: every rep is measured, and the benchmark depends on the weight that was lifted.

## What the research suggestion gets right, and what it doesn't

**Helpful:**

- **Object detection can find the dumbbell.** YOLO-style detectors (or SAM 3.1 with the prompt "dumbbell") put a box around it.
- **The bar path can be tracked.** A detector's box can be followed across frames. In a curl the dumbbell sits in the hand, so the wrist point that pose tracking already gives us *is* the bar path. No extra model is needed for tracking.

**Not possible from video:**

- **Reading the kilograms.** A camera cannot see "5 kg".
- **Using size as a proxy.** An adjustable dumbbell is as long at 2.5 kg as at 10 kg, and a water bottle can stand in for a light one.
- **Using angles as a proxy.** The body angles depend on how heavy the weight is *for that person*: a strong adult curls 10 kg with the same upright form a child shows with 2 kg. So "5 kg gives this angle, 10 kg gives that angle" is not true across people.

**What DeepFit does instead** (the approach used by velocity-based-training devices):

1. **The athlete picks the weight:** No weight/bottle, 1, 2, 3, 5, 7.5, 10 kg, or any other value.
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

**All constants are starter values.** `export_curl_dataset.py` writes the real dataset (one row per rep, athletes pseudonymous) so they can be replaced with values learned from field testing. An athlete who tests at two weights gives their own load-velocity line, the standard way to measure strength without a maximal lift.

## Where it shows

**Website (`/ex/dumbbell_curls`):**

- A weight picker.
- Live chips showing the last rep's speed, elbow angle and clean / swing.
- The result says "14 reps × 5 kg", the target for that weight, a table (clean reps, speed first → last, elbow angle vs expected, swing/drift vs limits, 1RM, next weight, weight check) and a bar chart of each rep's speed (green = clean).

**Phone app:**

- The same weight picker on the test screen.
- The weight is sent with the upload.
- The server re-runs the test with it.
- The result screen shows the same analysis.

**Talent Passport:**

- Shows "10 reps × 5 kg" and the weighted-curl panel.
- **The weight is part of the signature**, so changing it later makes the passport NOT VALID. Older results without a weight still verify.

**Counting is unchanged:** same thresholds, same feedback and events. The phone app's on-device engine still matches the server: all 30 parity cases were regenerated and are identical.

## Tested here

`test_curl_load.py` has 36 checks:

- Speed, angle, swing and drift are measured.
- Swinging or drifting reps are not clean.
- Fatigue is detected and the right 1RM formula is chosen.
- The benchmark table ordering, and lifting above the max rated Excellent.
- The SAM box near/far from the hand (mocked).
- The signed weight.
- Phone upload → server re-run → 5 kg benchmark → passport page.
- Impossible weights ignored, the curl page picker, and the dataset export.

**Not tested here:** a real camera with a real dumbbell, and the live SAM 3.1 call.
