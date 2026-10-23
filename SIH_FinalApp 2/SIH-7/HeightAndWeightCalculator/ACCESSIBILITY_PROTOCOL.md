# DeepFit - accessible testing protocol (blind & deaf athletes)

> This is DeepFit's **proposed** protocol. It is not an official SAI / Khelo India / Paralympic rule set. Review it with a
> physical-education teacher or para-sport coach before using results for selection.

## 1. Who uses which mode

| Mode | For | How the app behaves |
|---|---|---|
| 🔊 **Blind / low vision** (`?mode=blind`) | Athletes with visual impairment (para-sport classes B1 = no/very little sight, B2-B3 = partial sight). Default for athletes registered through the *Blind Person* flow. | Everything is spoken: instructions, face check, 3-2-1 countdown with beeps, each rep, form faults, "30 / 10 seconds left", the result and the next test. Large buttons and keyboard shortcuts: **V** verify, **Space** start/stop, **I** repeat instructions, **N** next test. Screen-reader live region announces the same text. |
| 🖐️ **Deaf / hard of hearing** (`?mode=deaf`) | Athletes with hearing impairment. Linked from the *Deaf & Other* page. | Nothing depends on sound: huge countdown numbers on the video, **green flash** for every counted rep, **red border** for a form fault, large captions of every instruction, phone vibration. |
| 👁️ **Standard** | Everyone else | Normal on-screen feedback. |

## 2. Rules that apply to every test

1. **Identity first.** The athlete's face is matched to the registration photo before the test and re-checked every 2 s. A helper may set up the athlete but must step out of the camera view before *Start* (otherwise the check fails: more than one person).
2. **Same counting rules** for all modes - the camera judges the same angles, so results are comparable. Only the *guidance* and the *benchmark* differ.
3. **Separate benchmarks** per population (`exercise_benchmarks.csv`, column `population` = standard / blind / deaf). Starter values are deliberately low; replace them after field testing.
4. **Safety.** Clear 2 m around the athlete, non-slip mat, no obstacles on run lanes. A coach stops the test if the athlete is unsafe.
5. **Record adaptations** (e.g. guide runner, fingertip wall support) - they are part of the result's context.

## 3. Test-by-test

### 🏋️ Sit-ups

- **Camera:** side · **Duration:** 60 s · **Result:** reps in reps (higher is better)
- **Scoring:** One rep = from lying (torso under 20° from the floor) to sitting up (over 55°) and back down.
- **Blind / low vision:** Spoken count after every rep; Spoken time left at 30 s and 10 s; A helper may place the athlete on the mat, then steps out of view
- **Deaf / hard of hearing:** Green flash on every counted rep; Big on-screen countdown and captions
- **Starter target (male, 16-18):** standard 10.0 · blind 8.5 · deaf 10.0 reps

### 🔄 Partial Curl-up  *(Khelo India)*

- **Camera:** side · **Duration:** 60 s · **Result:** reps in reps (higher is better)
- **Scoring:** One rep = lift shoulders until the torso is about 25° off the floor, then lower until the head is back down.
- **Blind / low vision:** Spoken count and 'lower down' / 'curl up' cues; Tactile strip on the mat marks how far the hands slide
- **Deaf / hard of hearing:** Green flash per counted rep, red border when a rep is not counted; Captions show 'curl up' / 'lower down'
- **Starter target (male, 16-18):** standard 10.0 · blind 8.5 · deaf 10.0 reps

### 💪 Push-ups  *(Khelo India)*

- **Camera:** side · **Duration:** 60 s · **Result:** reps in reps (higher is better)
- **Scoring:** One rep = lower until the elbows bend to about 90°, then push up until the arms are straight. The body must stay straight.
- **Blind / low vision:** Spoken count; spoken 'keep your body straight' when hips sag; Optional tactile marker (folded towel) under the chest to feel the bottom position
- **Deaf / hard of hearing:** Green flash per counted rep, red border when the body line breaks
- **Starter target (male, 16-18):** standard 5.0 · blind 4.2 · deaf 5.0 reps

### 🤸 Modified Push-ups (knees)  *(Khelo India)*

- **Camera:** side · **Duration:** 60 s · **Result:** reps in reps (higher is better)
- **Scoring:** Same as push-ups, but the straight line is from shoulders to knees.
- **Blind / low vision:** Spoken count; spoken 'keep your body straight' when hips sag; Optional tactile marker (folded towel) under the chest to feel the bottom position
- **Deaf / hard of hearing:** Green flash per counted rep, red border when the body line breaks
- **Starter target (male, 16-18):** standard 5.0 · blind 4.2 · deaf 5.0 reps

### 🧱 Plank Hold

- **Camera:** side · **Duration:** 180 s · **Result:** hold_time in s (higher is better)
- **Scoring:** Time starts when you are in a straight plank and stops when the body line breaks for more than 2 seconds (or at 3 minutes).
- **Blind / low vision:** Spoken time every 10 s; Spoken warning 'hips' the moment the line breaks, before the 2-second grace ends
- **Deaf / hard of hearing:** Large running clock; screen border turns red when the line breaks
- **Starter target (male, 16-18):** standard 20.0 · blind 17.0 · deaf 20.0 s

### 🦵 Squats

- **Camera:** side · **Duration:** 60 s · **Result:** reps in reps (higher is better)
- **Scoring:** One rep = bend until the knee angle is under 100° (thighs about parallel), then stand fully up.
- **Blind / low vision:** Spoken count; a chair behind the athlete can mark depth by touch (tap and rise)
- **Deaf / hard of hearing:** Green flash per rep, red border when the chest drops too far forward
- **Starter target (male, 16-18):** standard 15.0 · blind 12.8 · deaf 15.0 reps

### ⭐ Jumping Jacks

- **Camera:** front · **Duration:** 60 s · **Result:** reps in reps (higher is better)
- **Scoring:** One rep = jump to arms overhead + feet wide, then back to arms down + feet together.
- **Blind / low vision:** Spoken count after every rep
- **Deaf / hard of hearing:** Green flash per rep; big rep counter and captions
- **Starter target (male, 16-18):** standard 20.0 · blind 17.0 · deaf 20.0 reps

### 🏋️‍♂️ Dumbbell Curls

- **Camera:** front · **Duration:** 60 s · **Result:** reps in reps (higher is better)
- **Scoring:** Each arm counts separately: curl until the elbow angle is under 55°, lower until it is over 150°.
- **Blind / low vision:** Spoken 'left' / 'right' counts; Helper hands over the weights, then steps out of view
- **Deaf / hard of hearing:** Green flash per rep; captions show which arm was counted
- **Starter target (male, 16-18):** standard 10.0 · blind 8.5 · deaf 10.0 reps

### ⬆️ Vertical Jump

- **Camera:** side · **Duration:** 90 s · **Result:** max_height in cm (higher is better)
- **Scoring:** Jump height = how far the hips rise above their standing height, converted to cm using your height. Best of 3 jumps.
- **Blind / low vision:** Spoken 'ready - jump' after calibration; Clap or beep marks the start of each attempt
- **Deaf / hard of hearing:** Caption shows 'Ready - jump!' after calibration; green flash with the height after each jump
- **Starter target (male, 16-18):** standard 15.0 · blind 10.5 · deaf 15.0 cm

### ↔️ Standing Broad Jump

- **Camera:** side · **Duration:** 90 s · **Result:** distance in cm (higher is better)
- **Scoring:** Distance = how far the ankles travel from take-off to landing, converted to cm using your height. Best of 3 jumps.
- **Blind / low vision:** Tactile start line (tape) and a helper's voice from the landing area for direction; Spoken distance after each jump
- **Deaf / hard of hearing:** Caption shows 'Ready - jump!'; distance shown in large text and captions
- **Starter target (male, 16-18):** standard 80.0 · blind 56.0 · deaf 80.0 cm

### 🙆 Sit and Reach  *(Khelo India)*

- **Camera:** side · **Duration:** 45 s · **Result:** reach in cm (higher is better)
- **Scoring:** Reach = how far the fingertips go past the toes (negative if they stop before the toes), measured while the knees stay straight. Best held reach counts.
- **Blind / low vision:** A ruler with raised markings along the floor; spoken best reach after each hold
- **Deaf / hard of hearing:** Live reach shown in captions; green flash when a new best reach is held
- **Starter target (male, 16-18):** standard -5.0 · blind -6.5 · deaf -5.0 cm

### 🦩 Flamingo Balance  *(Khelo India)*

- **Camera:** front · **Duration:** 60 s · **Result:** falls in falls (lower is better)
- **Scoring:** Count the number of times the lifted foot touches the floor (or you lose balance) in 60 seconds of balancing. Fewer is better.
- **Blind / low vision:** Proposed: allowed one fingertip of light touch on a wall (record 'touch support' with the result); Spoken count of falls and time left
- **Deaf / hard of hearing:** Same rules; falls flash on screen; Note: some deaf athletes have inner-ear balance differences - use the deaf benchmark
- **Starter target (male, 16-18):** standard 10.0 · blind 14.3 · deaf 12.5 falls

### 👋 Plate Tapping  *(Khelo India)*

- **Camera:** front · **Duration:** 60 s · **Result:** time in s (lower is better)
- **Scoring:** Time to complete 25 left-right cycles. Lower is better.
- **Blind / low vision:** Use two physical plates at arm's length; a short beep confirms each valid touch; Helper guides the hand to each plate once before the test
- **Deaf / hard of hearing:** Target lights up when touched; cycle counter in large text
- **Starter target (male, 16-18):** standard 30.0 · blind 42.9 · deaf 30.0 s

### 🏃 50 m Dash  *(Khelo India)*

- **Camera:** not used (coach-timed) · **Duration:** until finished · **Result:** time in s (lower is better)
- **Scoring:** Time in seconds (coach-timed). Lower is better.
- **Blind / low vision:** Run with a guide runner on a tether (as in para-athletics) or along a guide rope; Audio 'Go' signal
- **Deaf / hard of hearing:** Visual start: flag drop or start light instead of a whistle
- **Starter target (male, 16-18):** standard 12.0 · blind 17.1 · deaf 12.0 s

### 🏟️ 600 m Run/Walk  *(Khelo India)*

- **Camera:** not used (coach-timed) · **Duration:** until finished · **Result:** time in s (lower is better)
- **Scoring:** Time in seconds (coach-timed). Lower is better.
- **Blind / low vision:** Guide runner with tether; lap count announced by the guide
- **Deaf / hard of hearing:** Visual start; lap count shown on a board
- **Starter target (male, 16-18):** standard 300.0 · blind 428.6 · deaf 300.0 s

### 📐 Growth Measures (sitting height)

- **Camera:** side · **Duration:** 120 s · **Result:** maturity_offset in yrs (higher is better)
- **Scoring:** Measures sitting height and leg length, then estimates how many years you are from your growth spurt (Mirwald equation). Late developers get extra credit in the Hidden Potential Index.
- **Blind / low vision:** A helper marks the spot and places the chair; the app says when to stand and when to sit; Spoken result at the end
- **Deaf / hard of hearing:** Large 'STAND' / 'SIT' captions with a progress bar for each hold
- **Target:** none (this is a measurement, not a scored test)

### 🧠 Coachability Challenge

- **Camera:** front · **Duration:** 300 s · **Result:** coachability in pts (higher is better)
- **Scoring:** Each try is compared with the pattern: a wrong, missed or extra move is 1 error, a late move is half an error. Your score is how much your errors drop from try 1 to the last tries (learning speed), plus how accurate you are at the end.
- **Blind / low vision:** Every move of the pattern is spoken before each try, with its step number; A tone confirms each move the camera recognises; the tip is spoken; Steps are relative to the athlete's own body (your left), so no visual reference is needed
- **Deaf / hard of hearing:** Pattern shown as numbered cards; the current step lights up; Tip shown in large captions; green / red flash for right / wrong moves
- **Starter target (male, 16-18):** standard 30.0 · blind 25.5 · deaf 30.0 pts

## 4. After the tests - what happens next

1. Each test ends with a **result card**: value, rating (Needs work / Fair / Good / Excellent vs the athlete's age-group target) and a **Next test** button (spoken in blind mode, press **N**).
2. The **All Tests** page (`/tests`) shows progress (x of 18 done, including height & weight), the recommended next test (Khelo India battery first) and a report table.
3. Blind athletes: after the audio pre-tests (reaction + Q&A) the results page now has **Continue to physical tests (audio guided)**.
4. Deaf athletes: the *Deaf & Other* page links to **All Fitness Tests (visual cues)**.
5. The **AI Coach** chatbot can read all results and explain them ("How did I do?").

## 5. Audio mirror (blind mode)

In blind mode a soft continuous tone plays during the test. Its pitch rises as the body gets closer to the correct position (220 Hz far → 880 Hz correct) and becomes a steady, gently pulsing high tone when the position is right. It quiets automatically while the app is speaking. Press **M** to turn it on or off. Exercises with a mirror: sit-ups, partial curl-up, push-ups (both), plank, squats, sit and reach, flamingo balance. The same signal drives the on-screen *Form meter* for everyone.

## 6. Tuning

All thresholds are constants at the top of each class in `exercise_engine.py` (e.g. `PushUps.DOWN = 95` degrees). Benchmarks: edit `exercise_benchmarks.csv` or change `STARTER` in `benchmarks.py` and run `python benchmarks.py`.
