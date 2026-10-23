# DeepFit Arena: the game is the trial

**One line:** a 3-minute full-body camera game that runs in any browser. Hidden inside it is a sports-science talent screen covering reflexes, agility, power, game reading, learning speed and heart-rate recovery. Meta's models act as the game master, the measuring tape, the ears and the artist.

Open `/arena`. No sign-up, no app install and no special hardware are needed: a laptop or phone camera is enough.

---

## Why it matters

India's talent trials reach the children who are already in a sports system. A child in a village does not sign up for a "fitness test", but they will play a game. In the Arena:

- Every move in the game is also a measurement.
- Every measurement is recalculated by the server and signed.
- The child walks away with a talent profile, sports to try, a coach's note in their own language and a verified card that a coach can scan.

## It looks and plays like a game

- **You are inside the game.** The camera cuts the player out of their room (MediaPipe segmentation, on the device) and drops them into each level's world, with a glow around them. If the cut-out isn't available, or the player picks "Cartoon avatar" in Settings, a cartoon avatar copies every move instead.
- **Six worlds, all drawn in code** (no image downloads), each with its own music loop:
  - a kabaddi court at sunset (crowd, bunting, palms, dhol beat);
  - a jungle track;
  - a village street;
  - a heart-scanner lab;
  - a cricket stadium at night (floodlights);
  - a disco dance floor.
- **Game feel:**
  - a title screen;
  - "LEVEL 2/6" intro cards and a 3-2-1-GO countdown;
  - points, plus combo multipliers for streaks (×1.5 → ×2.5);
  - floating "+203 / PERFECT!" text, confetti, screen shake and crowd cheers;
  - 1–3 stars per level;
  - a rank at the end (Rookie / Rising Star / Pro / Legend);
  - a personal best and a **leaderboard** (today / all time).
- **The points are honest.** `arena_score.points()` computes them from the raw measurements with the same rules the page uses. The server recomputes them, signs them, and the share card turns **NOT VALID** if they are edited. Demo-player games never appear on the real leaderboard.
- **Fonts are bundled** (Bungee, Baloo 2, Baloo Tammudu 2; SIL Open Font Licence), so the game works offline in Hindi and Telugu too.

## The levels and what each one secretly measures

| Level (world) | What the player does | Trait | How it is measured |
|---|---|---|---|
| Get ready | Stands still, whole body in the corner brackets | (calibration) | Body length in pixels → cm per pixel. **SAM 3.1** boxes the whole person, head to feet, to correct the scale. |
| 1 Raider Dodge (kabaddi court) | A kabaddi raider charges in from one side; step away | **Reflexes**, **Agility** | Reaction time from the raider appearing to the first hip movement. Moves under 120 ms are treated as guesses. Also dodge success and peak sideways speed. |
| 2 Log Jump (jungle) | Jump when the rolling log reaches the feet; a live height meter shows the jump | **Power** | Hip rise during the timing window × cm per pixel. |
| 3 Bull Run (village street) | A bull chases you; run on the spot (fast feet keep it back) | (raises the heart rate) | Steps counted from the knees swapping. |
| 4 Heart Scan, and the final scan (lab) | Face close to the camera, stay still inside the scanner rings | **Heart recovery** | Remote photoplethysmography (the POS method) on forehead and cheek skin. Measured right after the run and again at the end. **SAM 3.1** finds the face for the skin patch. |
| 5 Read the Bowler (night stadium) | A bowler runs in. The **floodlights go out** before the ball is seen, and the player steps to where it will go. The player is shown see-through during the run-up so the bowler is never hidden. | **Game reading** | Occlusion test, the method sports scientists use to measure anticipation. Accuracy is weighted by difficulty: easy clips cut late, hard clips cut before release. |
| 6 Dance-off (disco stage) | A dancing coach shows the moves in time with the music; remember them, then dance them in order. A tip follows each try. | **Learning speed** | Errors per try (edit distance), using the same scoring as the Coachability test. |

**Results:**

- A victory screen with rank, points, stars and leaderboard position.
- A six-trait radar chart and a talent score.
- The top three sports to try, matched against each sport's trait weights.
- A coach's note in the player's language.
- A next session that adapts to the player: faster raiders, more hard bowler clips and a longer combo where they are strong, and easier settings where they are weak.

## Upper-body game (no tripod needed)

Most players can't put the camera 3 m away. At the start the game watches for a few seconds:

- **Whole body in view** → the full game above.
- **Only the waist up** (sitting at a laptop, phone propped close) → the **upper-body game**:
  Shadow Boxing (punch the pads - raises the heart rate; a punch only counts after the fists come back to the body) →
  Heart Scan → Read the Bowler (**lean** left or right instead of stepping) → Dance-off (no squats or hands-on-hips) →
  final scan.
- Then: **"Unlock 3 bonus levels?"** Yes → step back, and Raider Dodge, Log Jump and Bull Run follow (the run becomes a
  full-body run). "Show my results" → results now. Voice ("yes" / "results") and keys (Space / R) work too.
- Reflexes, agility and power are shown as **"not measured" - never zero**. The result and the verified card say
  "Measured: upper body", and the scope is part of the signature.
- **Separate leaderboards** for full-body and upper-body runs. The server decides the scope from what was measured.
- During a full-body level, a spoken hint asks the player to step back if the feet leave the picture.

## The player in the world

- **Placed in the scene at a set size:** standing on the ground line, about 62 % of the screen tall, wherever the
  player stands; in the upper-body game a foreground player cut off at the waist. Every level draws through the same
  mapping, so raiders, logs and pads stay aligned with the body.
- **Lit like the scene:** the cut-out is auto-brightened (dim rooms) and tinted with the world's light - warm at the
  kabaddi sunset, cool under the stadium floodlights, pink on the dance floor.
- **Clean edges:** the person mask is smoothed over time, faint "ghost" areas are cut away, and a thin rim light
  replaces the thick glow. A soft shadow sits under the feet.
- **Automatic avatar:** when the room is too dark or the cut-out keeps breaking up for 3 s, the cartoon avatar takes
  over (with a small mirror), and the cut-out returns when the light is good again.
- Measurements use the raw camera frames, so none of this changes a score.

## Meta models: each one does a real job and each has a fallback

| Model | Job in the Arena | If it is not available |
|---|---|---|
| **Muse Spark** (`muse-spark-1.3`, JSON schema output) | Game master. Explains the profile in English, Hindi or Telugu, gives one home drill and a parents' tip, and **designs the next session** as structured JSON. The server clamps that JSON to safe limits. Also maps free-form voice commands to intents. | Rule-based coach in the same three languages. |
| **SAM 3.1** (`/v1/responses`) | Prompt "person" boxes the whole body for exact height calibration. Pose landmarks have no point on top of the head, so they under-measure. Prompt "face" boxes the face, so the pulse is read from skin. | Pose landmarks and eye positions. |
| **Muse Voice Transcribe** (`/v1/asr/transcribe`) | Hold the mic button (or the **V** key) and say "start", "repeat", "next" or "result" in English, Hindi or Telugu. Built for blind players and for children who can't read. | The on-screen buttons and keys. |
| **Muse Image** (`/v1/images/generations`) | A personal poster of the player's best-matched sport. It is an anonymous silhouette: no face and no text. | The button explains it needs the key. |

The page header shows a live chip (`Meta AI: SAM ✓ Spark ✓ Voice ✓`), so judges can see which models were used in a session. `GET /api/arena/status` reports the last error from each model, for example a 402 billing error.

## Inclusion

- **Blind / low-vision mode:**
  - Everything is spoken.
  - The raider is a stereo "whoosh" from its side.
  - Logs are a rising tone that pans in.
  - The bowler is a panned throw sound that stops early (an audio occlusion test).
  - A rising tone guides the face to the camera for the pulse check.
  - Voice commands are available throughout.
- **Deaf / hard-of-hearing mode:** large captions, green/red screen flashes and phone vibration.
- **Languages:** every instruction is in English, Hindi and Telugu (on-screen text and speech).

## Trust: what is protected and what is not (say this honestly to the jury)

- Body tracking runs on the player's device. **No video or photo is uploaded or stored**; only the numbers are sent.
- The browser sends the *raw* measurements. The server **recalculates every score itself** (`arena_score.py`) and ignores any scores the browser sends.
- The saved result is sealed with an SHA-256 hash of the raw measurements and an HMAC-SHA256 signature. The share card re-checks both, plus the recalculation, every time it is opened. Editing a score or a measurement turns it into **NOT VALID** (this is tested).
- Results played with the built-in simulated player are stamped **SIMULATED PLAYER**.
- **Limitation:** the Arena is a *screening game*. A determined cheater could fake the raw numbers in their own browser, because the measuring happens there. The *verified* trial is still the 15 camera tests, with face matching before and during the test and server-side re-runs. Use the Arena to find talent, then confirm it in the verified tests.
- Scales are starter values, to be tuned with field data. Pulse is a camera estimate, not a medical reading, and is dropped when its signal quality is low.

## Run it

1. In `.env` (never commit it): `MODEL_API_KEY=...`, `GROQ_API_KEY=...` and/or `GEMINI_API_KEY=...`. All are optional: without them the whole game still works, using the fallbacks. `llm.py` tries Meta's Muse Spark first; if Meta answers 401/402/403/404 (e.g. no credits) it moves on to Groq (Muse Spark open weights, then Llama 3.3 70B; Qwen for photos; Whisper for voice), then Google Gemini as the last resort, and skips a failed one for 15 minutes. When Gemini answers, the interface shows "DeepFit AI"; `/api/arena/status` lists the real models.
2. Start the app: `python app.py`.
3. On this computer, open **http://localhost:7860/arena**.
   - No camera, or recording the demo? Open **http://localhost:7860/arena?sim=1**. A simulated player plays the whole game.
4. **Phones need HTTPS for the camera.** A plain `http://192.168…` address will not open the camera on a phone. Use a tunnel, then set `PUBLIC_BASE_URL` to the tunnel's https address so QR codes point there:
   - `cloudflared tunnel --url http://localhost:7860`, or
   - `ngrok http 7860`
5. Optional: `pip install segno` draws QR codes on the server, which works offline. Otherwise the page uses a QR library from the internet.

Keys: **Space** start · hold **V** to speak · **M** sound on/off.

## 3-minute demo video outline

1. **0:00–0:20.** A child in a village ground; "Talent trials never reach her. A game can."
2. **0:20–1:30.** Play the Arena live, with the Telugu voice, and let the combo counter and the crowd show. Show the raider charging, the log jump, the bull run, the heart scanner, the floodlights going out, and the dance-off.
3. **1:30–2:00.** Results:
   - The radar chart and sports to try.
   - The Muse Spark coach speaking Telugu.
   - "Next session" changes to match her.
   - Muse Image poster.
4. **2:00–2:25.** Switch to blind mode with eyes closed: the stereo raider sound and a voice command ("మొదలుపెట్టు", "start").
5. **2:25–2:50.** Save, scan the QR on another phone → **✓ VERIFIED**. Edit a number in the database and scan again → **✗ NOT VALID**.
6. **2:50–3:00.** "No video leaves the phone. Four Meta models, each doing a real job. The game is the trial."

## Files

| File | Contents |
|---|---|
| `arena_blueprint.py` | Routes, Muse Spark coach and plan limits, save/sign/verify |
| `arena_score.py` | The server's scoring and sport matching |
| `meta_models.py` | Muse Spark (JSON schema), SAM 3.1 boxes, Muse Voice Transcribe, Muse Image; all return `None` on failure |
| `templates/arena.html`, `static/arena/arena.js`, `static/arena/arena.css` | The game: MediaPipe Pose + segmentation for the web, levels, points, rPPG, voice, the demo player |
| `static/arena/art.js` | Worlds, cartoon characters (raider, bowler, bull, dancing coach, avatar), logs, effects |
| `static/arena/sound.js` | Music loops per world, sound effects, spatial cues for blind players (all synthesised) |
| `static/arena/fonts/` | Bundled game fonts + their licences |
| `templates/arena_result.html` | The verified share card (radar drawn on the server, so it prints) |

**Tests**, run in the development container against an in-memory database:

- 49 scoring, points, leaderboard and route checks.
- 11 checks against a mocked Meta API (request shapes, clamping the plan from Muse Spark, a 402 falling back to the Hindi coach).
- Full games played by the simulated player in headless Chromium in English/standard and Hindi/deaf, plus Telugu screenshots at real speed. The pulse was read back as 102 → 83–84 bpm with quality 0.8–0.9. Points shown live matched the server's exactly. Save worked, and the scanned card showed VERIFIED.
- The real camera, the segmentation cut-out, MediaPipe from its CDN and the live Meta API were **not** tested here; test them on your Mac before recording. If the cut-out is slow on a weak laptop, choose "Cartoon avatar" in Settings.

## Before you submit (Meta hackathon, Indie track)

- **Read the Official Rules** (published before Oct 26) on **pre-existing work**:
  - DeepFit and this Arena were written **before** the hackathon window (Oct 26 – Nov 4).
  - If the rules only allow work started inside the window, or ask you to declare earlier work, follow them exactly: declare it, and show clearly what you build during the window. Your GitHub history shows the dates.
- Make sure the Meta API key you demo with has billing enabled. A 402 silently switches everything to the fallbacks, and the chip will show `·` instead of `✓`.
- Rotate any key that was ever pasted into a chat or committed.
