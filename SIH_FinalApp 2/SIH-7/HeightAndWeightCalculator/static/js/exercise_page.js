/*
 * DeepFit - shared logic for every test page (templates/exercise.html).
 *
 * Modes
 *   standard : normal on-screen feedback
 *   blind    : everything is spoken (instructions, countdown, every rep, faults, time left, result),
 *              beeps on events, big buttons, keyboard shortcuts, screen-reader live region
 *   deaf     : nothing depends on sound - huge countdown numbers, green flash per rep,
 *              red border on faults, large captions, phone vibration
 */
(function () {
    const EX = window.EX, CTX = window.EX_CTX;
    const $ = (id) => document.getElementById(id);
    const el = {
        verify: $('verify-btn'), start: $('start-btn'), stop: $('stop-btn'), speak: $('speak-btn'),
        feed: $('video-feed'), placeholder: $('placeholder'), verifyVideo: $('verify-video'),
        timer: $('timer-display'), timerLabel: $('timer-label'), timerBar: $('timer-progress'),
        status: $('session-status'), value: $('main-value'), invalid: $('invalid-count'),
        form: $('form-percentage'), formBar: $('form-progress'), identity: $('identity-verified'),
        feedback: $('feedback'), flash: $('flash'), countdown: $('countdown-overlay'), caption: $('caption'),
        live: $('sr-live'), result: $('result-card'), stopwatch: $('stopwatch'), height: $('height-input'),
    };
    let mode = CTX.mode || 'standard';
    let verified = !CTX.requireFace;
    let running = false, pollTimer = null, lastEventId = 0, lastFeedback = '', lastSpokenAt = 0;
    let announced = new Set(), resultShown = false, swStart = null, swTimer = null, nextUrl = null;

    // ------------------------------------------------------------ audio / visual helpers
    const synth = window.speechSynthesis;
    function say(text, interrupt) {
        if (el.live) el.live.textContent = text;
        if (mode !== 'blind' || !synth) return;
        if (interrupt) synth.cancel();
        const u = new SpeechSynthesisUtterance(text);
        u.rate = 1.05;
        synth.speak(u);
    }
    let audioCtx = null;
    function beep(freq = 880, ms = 120) {
        if (mode !== 'blind') return;
        try {
            audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
            const o = audioCtx.createOscillator(), g = audioCtx.createGain();
            o.frequency.value = freq; o.connect(g); g.connect(audioCtx.destination);
            g.gain.setValueAtTime(0.2, audioCtx.currentTime);
            o.start(); o.stop(audioCtx.currentTime + ms / 1000);
        } catch (e) { /* audio not available */ }
    }
    function flash(kind) {
        if (mode !== 'deaf' || !el.flash) return;
        el.flash.className = kind;
        setTimeout(() => { el.flash.className = ''; }, kind === 'ok' ? 350 : 900);
        if (navigator.vibrate) navigator.vibrate(kind === 'ok' ? 80 : [60, 60, 60]);
    }
    function caption(text) { if (el.caption) el.caption.textContent = text || ''; }

    // ------------------------------------------------------------ audio mirror
    // A continuous tone whose pitch rises as the body gets closer to the correct position
    // (220 Hz far -> 880 Hz correct). At >= 95% it becomes a steady, gently pulsing tone.
    const mirror = { on: false, osc: null, gain: null, lfo: null };
    function mirrorEnsure() {
        if (mirror.osc) return true;
        try {
            audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
            mirror.osc = audioCtx.createOscillator(); mirror.gain = audioCtx.createGain();
            mirror.osc.type = 'triangle'; mirror.gain.gain.value = 0;
            mirror.osc.connect(mirror.gain); mirror.gain.connect(audioCtx.destination);
            mirror.osc.start();
            return true;
        } catch (e) { return false; }
    }
    function mirrorSet(v) {
        const bar = $('meter-fill');
        if (bar) bar.style.width = (v == null ? 0 : Math.round(v * 100)) + '%';
        if (!mirror.on || !running || !mirrorEnsure()) { if (mirror.gain) mirror.gain.gain.setTargetAtTime(0, audioCtx.currentTime, 0.05); return; }
        const now = audioCtx.currentTime;
        if (v == null) { mirror.gain.gain.setTargetAtTime(0, now, 0.05); return; }
        const freq = 220 * Math.pow(2, 2 * v);
        mirror.osc.frequency.setTargetAtTime(v >= 0.95 ? 880 : freq, now, 0.06);
        const speaking = synth && synth.speaking;
        let vol = speaking ? 0.015 : 0.06;                      // duck under speech
        if (v >= 0.95) vol *= (Math.floor(now * 4) % 2 ? 1 : 0.6);   // gentle pulse = "hold it"
        mirror.gain.gain.setTargetAtTime(vol, now, 0.05);
    }
    function mirrorToggle(force) {
        mirror.on = force === undefined ? !mirror.on : force;
        const b = $('mirror-btn');
        if (b) { b.textContent = mirror.on ? '🔊 Audio mirror: on' : '🔈 Audio mirror: off'; b.setAttribute('aria-pressed', String(mirror.on)); }
        if (!mirror.on && mirror.gain && audioCtx) mirror.gain.gain.setTargetAtTime(0, audioCtx.currentTime, 0.05);
        if (mode === 'blind') say(mirror.on ? 'Audio mirror on. The tone rises as you get closer to the right position.' : 'Audio mirror off.', true);
    }

    // ------------------------------------------------------------ coachability panel
    let lastPhase = '';
    function renderCoach(s) {
        const pat = $('pattern');
        if (!pat || !s.pattern) return;
        $('pattern-code').textContent = '#' + s.pattern_code;
        const done = s.done_moves || [];
        pat.innerHTML = '';
        s.pattern.forEach((m, i) => {
            const d = document.createElement('div');
            let cls = 'step';
            if (s.phase === 'perform') {
                if (i < done.length) cls += done[i] === m.label ? ' ok' : ' bad';
                else if (i === done.length) cls += ' next';
            }
            d.className = cls;
            const b = document.createElement('b'); b.textContent = String(i + 1);
            d.appendChild(b); d.appendChild(document.createTextNode(m.label));
            pat.appendChild(d);
        });
        const tries = $('tries').children;
        for (let i = 0; i < tries.length; i++) {
            const t = s.tries[i];
            tries[i].innerHTML = '';
            tries[i].appendChild(document.createTextNode('Try ' + (i + 1)));
            const b = document.createElement('b');
            b.textContent = t ? t.errors : (i + 1 === s.current_try && s.phase === 'perform' ? '…' : '–');
            tries[i].appendChild(b);
            tries[i].style.border = (i + 1 === s.current_try && s.phase === 'perform') ? '1px solid #22d3ee' : '';
        }
        const phases = { ready: 'Stand still, arms down', preview: 'Learn the pattern…', perform: `Try ${s.current_try} of 5 - go!`,
                         review: 'Read the tip', done: 'Finished' };
        $('coach-phase').textContent = phases[s.phase] || '';
        const tip = $('coach-tip');
        const last = s.tries[s.tries.length - 1];
        if (last && (s.phase === 'review' || s.phase === 'ready' || s.phase === 'done')) { tip.style.display = 'block'; tip.textContent = 'Tip: ' + last.tip; }
        else if (s.phase === 'perform') tip.style.display = 'none';
        if (s.phase !== lastPhase && s.phase === 'perform') flash('ok');
        lastPhase = s.phase;
    }
    function curveSvg(errs) {
        const W = 300, H = 140, n = errs.length, max = Math.max(1, ...errs);
        const x = i => 30 + i * (W - 50) / Math.max(1, n - 1), y = e => 15 + (H - 40) * (1 - e / max);
        const pts = errs.map((e, i) => `${x(i)},${y(e)}`).join(' ');
        const dots = errs.map((e, i) => `<circle cx="${x(i)}" cy="${y(e)}" r="4" fill="#22d3ee"/><text x="${x(i)}" y="${H - 8}" fill="#94a3b8" font-size="11" text-anchor="middle">Try ${i + 1}</text><text x="${x(i)}" y="${y(e) - 8}" fill="#e6f0ff" font-size="11" text-anchor="middle">${e}</text>`).join('');
        return `<svg role="img" aria-label="Errors per try: ${errs.join(', ')}" width="100%" viewBox="0 0 ${W} ${H}"><polyline points="${pts}" fill="none" stroke="#22d3ee" stroke-width="3"/>${dots}</svg>`;
    }
    function showCountdown(n) {
        if (!el.countdown) return;
        if (n > 0 && (mode === 'deaf' || mode === 'blind')) {
            el.countdown.style.display = 'flex';
            el.countdown.textContent = n;
        } else {
            el.countdown.style.display = 'none';
        }
    }
    function fmt(sec) {
        sec = Math.max(0, Math.round(sec));
        return Math.floor(sec / 60) + ':' + String(sec % 60).padStart(2, '0');
    }
    function instructionsText() {
        return `${EX.name}. ${EX.setup.join('. ')}. How it is scored: ${EX.counting}` +
            (mode === 'blind' && EX.blind_adaptation.length ? ` Adaptations: ${EX.blind_adaptation.join('. ')}.` : '') +
            ' Press V to verify your face, then press space to start.';
    }

    // ------------------------------------------------------------ mode switch
    const notes = {
        standard: 'Standard mode.',
        blind: 'Audio guide on: instructions, countdown, every rep and your result are spoken. Keys: V verify, Space start/stop, I instructions, N next test.',
        deaf: 'Visual mode on: big countdown, green flash on every counted rep, red border on form faults, captions and vibration.'
    };
    function setMode(m) {
        mode = m;
        document.body.className = 'mode-' + m;
        document.querySelectorAll('.mode-bar button').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.mode === m)));
        $('mode-note').textContent = notes[m];
        const ab = $('adapt-blind'), ad = $('adapt-deaf');
        if (ab) ab.style.display = m === 'blind' ? '' : 'none';
        if (ad) ad.style.display = m === 'deaf' ? '' : 'none';
        try { localStorage.setItem('deepfit_mode', m); } catch (e) { }
        const url = new URL(window.location.href); url.searchParams.set('mode', m);
        history.replaceState(null, '', url);
        document.querySelectorAll('a[href^="/tests"]').forEach(a => { a.href = '/tests?mode=' + m; });
        if (m === 'blind' && !mirror.on) {      // audio mirror defaults to on for blind athletes
            mirror.on = true;
            const b = $('mirror-btn'); if (b) { b.textContent = '🔊 Audio mirror: on'; b.setAttribute('aria-pressed', 'true'); }
        }
        if (m === 'blind') say('Audio guide on. ' + instructionsText(), true);
    }
    document.querySelectorAll('.mode-bar button').forEach(b => b.addEventListener('click', () => setMode(b.dataset.mode)));
    setMode(mode);

    // ------------------------------------------------------------ identity
    async function verify() {
        if (!CTX.loggedIn) { say('Please log in first.', true); alert('Please log in or register first.'); return; }
        el.verify.disabled = true;
        el.verify.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Verifying...';
        say('Look at the camera. Checking your face.', true);
        try {
            if (window.VerifyView) { await VerifyView.prepare(); VerifyView.busy(); }
            const frame = window.VerifyView ? VerifyView.captureFrame() : null;
            const r = await fetch(CTX.verifyUrl, {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ frame_data: frame })
            });
            const res = await r.json();
            if (res.success && res.is_match) {
                verified = true;
                if (window.VerifyView) VerifyView.success();
                if (el.verifyVideo.srcObject) el.verifyVideo.srcObject.getTracks().forEach(t => t.stop());
                el.verify.innerHTML = '<i class="fas fa-check-circle"></i> Verified';
                el.identity.textContent = 'Verified ✓'; el.identity.style.color = '#4ade80';
                el.start.disabled = false; el.start.removeAttribute('title');
                el.status.textContent = 'Identity verified. Ready to start.';
                say('Identity verified. Press space to start the test.', true); beep(1200);
                flash('ok'); caption('Identity verified');
            } else {
                const msg = res.message || res.error || 'Face did not match';
                if (window.VerifyView) VerifyView.fail(msg);
                el.verify.disabled = false;
                el.verify.innerHTML = '<i class="fas fa-user-check"></i> Verify Identity';
                el.identity.textContent = 'Not verified'; el.identity.style.color = '#f87171';
                say(msg + '. Please try again.', true); beep(300, 300); flash('bad'); caption(msg);
            }
        } catch (e) {
            el.verify.disabled = false;
            el.verify.innerHTML = '<i class="fas fa-user-check"></i> Verify Identity';
            if (window.VerifyView) VerifyView.fail('Could not reach the server');
        }
    }

    // ------------------------------------------------------------ start / stop
    async function start() {
        if (!verified) { say('Please verify your identity first. Press V.', true); return; }
        if (running) return;
        el.start.disabled = true;
        const body = { mode, height_cm: el.height ? Number(el.height.value) : null };
        if (EX.key === 'growth_measures') {
            body.height_cm = Number($('in-height').value); body.weight_kg = Number($('in-weight').value);
            body.chair_cm = Number($('in-chair').value);
            if (!body.height_cm || !body.weight_kg || !body.chair_cm) {
                const m = 'Enter standing height, weight and chair height first.';
                el.status.textContent = m; say(m, true); caption(m); $('in-weight').focus(); return;
            }
        }
        if (EX.key === 'dumbbell_curls') {
            body.load_kg = Number($('in-load').value) || 0;
            body.load_detect = (detected && Number(detected.kg) === body.load_kg) ? detected : (body.load_kg ? { source: 'typed' } : null);
        }
        if (EX.key === 'height_weight') {
            const w = Number($('in-hw-weight').value) || null;
            body.weight_kg = w;
            body.weight_source = (scaleRead && w === Number(scaleRead.kg)) ? 'scale_photo' : 'typed';
            body.weight_detail = body.weight_source === 'scale_photo' ? scaleRead : null;
        }
        const r = await fetch(`/ex/${EX.key}/start`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
        const res = await r.json();
        if (res.status !== 'success') {
            el.start.disabled = false;
            el.status.textContent = res.message;
            say(res.message, true); caption(res.message);
            if (res.identity_required) {
                verified = false;
                el.verify.disabled = false;
                el.verify.innerHTML = '<i class="fas fa-user-check"></i> Verify Identity';
            }
            return;
        }
        running = true; resultShown = false; lastEventId = 0; announced = new Set(); lastFeedback = '';
        el.stop.disabled = false;
        if (EX.camera === 'none') {
            swStart = performance.now();
            swTimer = setInterval(() => { el.stopwatch.textContent = ((performance.now() - swStart) / 1000).toFixed(2); }, 50);
            el.status.textContent = 'Running… press Stop at the finish line';
            say('Go!', true); beep(1000, 300); flash('ok'); caption('GO!');
            return;
        }
        if (window.VerifyView && VerifyView.isVisible()) VerifyView.hide();
        el.feed.src = `/ex/${EX.key}/video_feed?t=${Date.now()}`;
        el.feed.style.display = 'block';
        el.placeholder.style.display = 'none';
        el.status.textContent = 'Get ready…';
        say('Get ready.', true);
        pollTimer = setInterval(poll, mode === 'blind' ? 200 : 400);
    }

    async function stop() {
        if (!running) return;
        if (EX.camera === 'none') {
            clearInterval(swTimer);
            const secs = (performance.now() - swStart) / 1000;
            running = false; el.stop.disabled = true;
            const value = prompt('Confirm the time in seconds (edit if the coach used a separate stopwatch):', secs.toFixed(2));
            if (value === null) { el.start.disabled = false; return; }
            const r = await fetch(`/ex/${EX.key}/manual`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ value: Number(value) }) });
            const res = await r.json();
            if (res.status === 'success') showResult(res.result); else { alert(res.message); el.start.disabled = false; }
            return;
        }
        el.stop.disabled = true;
        const r = await fetch(`/ex/${EX.key}/stop`, { method: 'POST' });
        const res = await r.json();
        endRun();
        if (res.result) showResult(res.result);
    }

    function endRun() {
        running = false;
        clearInterval(pollTimer); pollTimer = null;
        el.feed.src = ''; el.feed.style.display = 'none';
        el.placeholder.style.display = 'flex';
        el.stop.disabled = true; el.start.disabled = !verified;
        showCountdown(0);
        mirrorSet(null);
    }

    // ------------------------------------------------------------ live stats
    async function poll() {
        let s;
        try { s = await (await fetch(`/ex/${EX.key}/stats`)).json(); } catch (e) { return; }
        if (!s || s.active === undefined) return;

        // countdown
        const cd = Math.ceil(s.countdown || 0);
        showCountdown(cd);
        if (cd > 0 && !announced.has('cd' + cd)) { announced.add('cd' + cd); say(String(cd), true); beep(660); }
        if (cd === 0 && s.active && !announced.has('go')) { announced.add('go'); say('Go!', true); beep(1000, 250); flash('ok'); }

        el.status.textContent = s.result ? 'Finished' : (cd > 0 ? 'Get ready…' : (s.active ? 'Test running' : 'Stopped'));
        // numbers
        el.value.textContent = s.value;
        if (el.invalid) el.invalid.textContent = s.invalid_reps;
        if (el.form) { el.form.textContent = s.form_percentage + '%'; el.formBar.style.width = s.form_percentage + '%'; }
        el.feedback.textContent = s.feedback;
        caption(s.feedback);
        if (s.mirror !== undefined) {
            if (s.mirror != null) { $('meter-row').style.display = ''; $('mirror-label').textContent = s.mirror_label || ''; }
            mirrorSet(cd > 0 ? null : s.mirror);
        }
        if (s.load && $('load-live')) {
            const L = s.load, r = L.last;
            $('load-live').innerHTML = L.load_kg ? `<span>${L.load_kg} kg</span><span>Clean reps ${L.clean_reps}</span>` +
                (r ? `<span>Last: ${r.speed != null ? r.speed + ' m/s' : '–'}</span><span>Elbow ${r.top_angle}°</span>` +
                     `<span class="${r.clean ? 'ok' : 'bad'}">${r.clean ? '✓ clean' : '✗ ' + (r.swing_pct > 15 ? 'body swing' : 'elbow drift')}</span>` : '') : '';
        }
        if (s.height && $('hw-live')) {
            const H = s.height;
            const what = H.reference === 'a4' ? 'A4' : 'sheet';
            $('hw-live').innerHTML =
                `<span class="${H.floor ? 'ok' : 'bad'}">${H.floor ? '✓' : '…'} FLOOR ${what}</span>` +
                `<span class="${H.top ? 'ok' : 'bad'}">${H.top ? '✓' : '…'} TOP ${what}</span>` +
                `<span>Samples ${Math.min(H.samples, H.need)}/${H.need}</span>` + (H.live_cm ? `<span>Now ≈ ${H.live_cm} cm</span>` : '');
        }
        if (EX.key === 'coachability') {
            renderCoach(s);
            el.value.textContent = Math.round(s.score);
        }
        if (s.remaining != null && s.duration) {
            el.timer.textContent = fmt(s.remaining);
            el.timerBar.style.width = (100 * (1 - s.remaining / s.duration)) + '%';
            for (const mark of [30, 10]) {
                if (s.remaining <= mark && s.remaining > mark - 2 && !announced.has('t' + mark) && s.duration > mark + 5) {
                    announced.add('t' + mark); say(`${mark} seconds left`);
                }
            }
        } else {
            el.timer.textContent = fmt(s.elapsed);
            el.timerLabel.textContent = 'Elapsed';
        }
        const idText = { verified: 'Verified ✓ (live)', mismatch: `MISMATCH ${s.identity_strikes}/3`,
                         face_hidden: `Face hidden ${s.identity_strikes}/3`, no_face: 'Face not visible', pending: 'Checking…' };
        el.identity.textContent = idText[s.identity_status] || 'Verified ✓';
        el.identity.style.color = (s.identity_status === 'mismatch' || s.identity_status === 'face_hidden') ? '#f87171' : '#4ade80';

        // events: reps / faults / ticks
        for (const ev of (s.events || [])) {
            if (ev.id <= lastEventId) continue;
            lastEventId = ev.id;
            if (ev.kind === 'rep') { say(ev.text, true); beep(1100, 90); flash('ok'); }
            else if (ev.kind === 'fault') { say(ev.text, true); beep(250, 250); flash('bad'); }
            else if (ev.kind === 'tap') { beep(ev.text === 'left' ? 700 : 900, 60); flash('ok'); }
            else if (ev.kind === 'move') { const ok = ev.text.startsWith('✓'); beep(ok ? 1200 : 300, 90); flash(ok ? 'ok' : 'bad'); }
            else if (ev.kind === 'go') { say('Go!', true); beep(1000, 250); flash('ok'); }
            else if (ev.kind === 'tip') { say(ev.text, true); }
            else { say(ev.text); }
        }
        // position guidance (spoken at most every 5 s, only when it changes)
        if (s.feedback !== lastFeedback && Date.now() - lastSpokenAt > 5000 && /visible|turn|step|stand still|lift|sit side|face the/i.test(s.feedback)) {
            say(s.feedback); lastSpokenAt = Date.now();
        }
        lastFeedback = s.feedback;

        if (s.identity_error && !resultShown) {
            endRun(); resultShown = true;
            say('Test stopped. A different person was detected.', true); flash('bad');
            alert('A different person was detected. Test stopped - only the registered athlete can take it.');
            return;
        }
        if (s.result && !resultShown) { endRun(); showResult(s.result); }
        else if (!s.active && running && !s.result) { endRun(); }
    }

    // ------------------------------------------------------------ result card
    function showResult(r) {
        if (!r) return;
        resultShown = true;
        const b = r.benchmark || {};
        const val = (Math.round(r.value * 10) / 10) + ' ' + r.unit;
        $('result-value').textContent = val;
        const rating = $('result-rating');
        rating.textContent = b.rating || 'Saved';
        rating.className = 'rating ' + (b.rating || '').replace(' ', '-');
        $('result-target').textContent = b.available
            ? `Target for your age group (${b.age_band}, ${b.population}): ${b.higher_is_better ? '≥' : '≤'} ${b.target} ${b.unit}` : '';
        $('result-note').textContent = r.saved === false ? 'Not saved - the identity check failed.' :
            (r.incomplete ? 'Not completed within the time limit.' : '');
        const extra = $('result-extra'); extra.innerHTML = '';
        if (r.coachability) {
            const c = r.coachability;
            rating.textContent = (b.rating || '') + (c.percentile != null ? ` · ${c.percentile}th percentile*` : '');
            extra.innerHTML = curveSvg(c.errors_per_try || []);
            const p = document.createElement('p'); p.style.color = '#94a3b8'; p.style.fontSize = '.85rem';
            p.textContent = (c.reduction_pct ? `Errors fell ${c.reduction_pct}% from try 1. ` : '') + (c.note || '') + ' *Starter norm.';
            extra.appendChild(p);
        }
        if (r.load_kg && r.load_analysis) {
            const A = r.load_analysis, chk = r.load_check || {};
            $('result-value').textContent = `${r.value} reps × ${r.load_kg} kg`;
            if (b.available) $('result-target').textContent = b.target > 1
                ? `Target with ${b.benchmark_load_kg} kg for your group (${b.age_band}): ≥ ${b.target} clean reps - you did ${A.clean_reps}`
                : (b.note || '');
            const seen = chk.seen === true ? '✓ dumbbell seen by SAM 3.1' : chk.seen === false ? '⚠ SAM 3.1 did not see a dumbbell in the hand' : 'not checked (' + (chk.reason || 'no Meta API key') + ')';
            const rows = [
                ['Clean reps (no swing, elbows pinned)', `${A.clean_reps} of ${A.reps}`],
                ['Lifting speed, first reps → last reps', A.first_speed_m_s != null ? `${A.first_speed_m_s} → ${A.last_speed_m_s ?? '–'} m/s` + (A.velocity_loss_pct != null ? ` (slowed ${A.velocity_loss_pct}%)` : '') : '–'],
                ['Elbow angle at the top', A.mean_top_angle_deg != null ? `${A.mean_top_angle_deg}° (expected ~${b.expected_top_angle_deg ?? '–'}° at this weight)` : '–'],
                ['Body swing / elbow drift', `${A.mean_swing_pct ?? '–'}% / ${A.mean_drift_pct ?? '–'}% (limits ${b.max_swing_pct ?? 15}% / ${b.max_elbow_drift_pct ?? 25}%)`],
                ['How heavy it was for you', A.intensity ? A.intensity : '–'],
                ['Estimated one-rep max (each arm)', A.est_1rm_kg ? `≈ ${A.est_1rm_kg} kg` + (A.est_1rm_note ? ` - ${A.est_1rm_note}` : '') : 'needs a heavier dumbbell'],
                ['Next time try', A.next_load_kg ? `${A.next_load_kg} kg` : '–'],
                ['How the weight was found', (() => { const d = r.load_detect || {};
                    return d.source === 'label' ? `read "${d.label_text || r.load_kg + ' kg'}" on the dumbbell` :
                           d.source === 'estimate' ? 'estimated from its look, confirmed by you' : 'picked by you'; })()],
                ['Weight vs benchmark', (b.weight_check && b.weight_check.text) ? `${b.weight_check.ok === false ? '⚠ ' : b.weight_check.ok ? '✓ ' : ''}${b.weight_check.text}` : '–'],
                ['Dumbbell in the hand', seen],
            ];
            const t = document.createElement('table'); t.className = 'load-table';
            t.innerHTML = rows.map(([k, v]) => `<tr><td>${k}</td><td><b>${v}</b></td></tr>`).join('');
            extra.appendChild(t);
            const sp = (r.reps_detail || []).map((x) => x.speed || 0), mx = Math.max(0.1, ...sp);
            if (sp.length) {
                const W = 300, H = 60, bw = W / sp.length;
                extra.insertAdjacentHTML('beforeend', `<svg viewBox="0 0 ${W} ${H + 14}" style="width:100%;max-width:360px;margin-top:8px" role="img" aria-label="Lifting speed of each rep">` +
                    sp.map((v, i) => `<rect x="${i * bw + 1}" y="${H - H * v / mx}" width="${bw - 2}" height="${H * v / mx}" fill="${(r.reps_detail[i] || {}).clean ? '#22c55e' : '#f87171'}"/>`).join('') +
                    `<text x="0" y="${H + 12}" fill="#94a3b8" font-size="10">speed of each rep (green = clean)</text></svg>`);
            }
        }
        if (EX.key === 'height_weight') {
            const M = r.measurement || {};
            $('result-value').textContent = r.height_cm ? `${r.height_cm} cm` + (r.weight_kg ? ` · ${r.weight_kg} kg` : '') : 'Not measured';
            rating.textContent = r.bmi ? `BMI ${r.bmi}` + (r.bmi_category ? ` · ${r.bmi_category}` : '') : (r.height_cm ? 'Height measured' : 'Try again');
            rating.className = 'rating ' + ({ Healthy: 'Good', Underweight: 'Fair', Overweight: 'Fair', Obese: 'Needs-work' }[r.bmi_category] || '');
            $('result-target').textContent = r.bmi_note || '';
            const ws = r.weight_source === 'scale_photo' ? `read from your scale photo (${(r.weight_detail || {}).reading ?? r.weight_kg} ${(r.weight_detail || {}).unit || 'kg'})`
                     : r.weight_kg ? 'typed' : 'not given - add it for the BMI';
            const rows = [
                ['Height', r.height_cm ? `${r.height_cm} cm` : '–'],
                ['How sure', M.stable ? `${M.samples} frames agreed within ±${M.spread_cm} cm (accuracy ≈ ±1 cm)` : 'did not settle - stand still against the wall'],
                ['Measured with', (M.reference === 'marker' ? 'DeepFit FLOOR + TOP sheets' : M.reference === 'a4' ? 'two A4 sheets' : '–') +
                    (M.camera_distance_cm ? ` · camera ${(M.camera_distance_cm / 100).toFixed(1)} m away, ${M.camera_height_cm} cm high` : '')],
                ['Weight', r.weight_kg ? `${r.weight_kg} kg - ${ws}` : ws],
                ['BMI', r.bmi ? `${r.bmi}${r.bmi_category ? ' (' + r.bmi_category + ')' : ''}` : '–'],
            ];
            const t = document.createElement('table'); t.className = 'load-table';
            t.innerHTML = rows.map(([k, v]) => `<tr><td>${k}</td><td><b>${v}</b></td></tr>`).join('');
            extra.appendChild(t);
            if (r.incomplete) $('result-note').textContent = 'Height did not settle in time: ' + (r.feedback || 'stand still against the wall next to the marker') + '.';
        }
        if (r.maturity) {
            const m = r.maturity;
            rating.textContent = m.status ? `${m.status} developer` : 'Measured';
            $('result-value').textContent = `${m.sitting_height_cm} cm sitting height`;
            const p = document.createElement('p'); p.style.color = '#cbd5e1';
            p.textContent = m.maturity_offset != null
                ? `About ${Math.abs(m.maturity_offset).toFixed(1)} years ${m.maturity_offset < 0 ? 'before' : 'after'} the growth spurt (predicted at age ${m.predicted_aphv}; average ${m.mean_aphv}). ${m.note}`
                : 'Add your weight and age to get the maturity estimate.';
            extra.appendChild(p);
        }
        const pl = $('passport-line');
        if (r.passport_url) { pl.style.display = ''; $('passport-link').href = r.passport_url; } else pl.style.display = 'none';
        // optional hand check: what a person counted / timed / measured, kept next to the result for /validation
        const hc = $('hand-check'), pr = r.hand_check_prompt;
        if (pr && r.result_id && r.passport) {
            hc.style.display = '';
            $('hc-label').textContent = pr.label + '. Type it here to compare with the app.';
            $('hc-unit').textContent = pr.unit;
            $('hc-value').value = '';
            $('hc-status').textContent = '';
            $('hc-save').onclick = async () => {
                const v = $('hc-value').value;
                if (v === '') { $('hc-status').textContent = 'Type the number first.'; return; }
                $('hc-save').disabled = true;
                try {
                    const res = await fetch('/api/hand_check', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ rid: r.result_id, tok: r.passport.token, value: Number(v) }) });
                    const d = await res.json();
                    $('hc-status').textContent = d.ok
                        ? (d.agrees ? `✓ Saved - the app (${d.app}) agrees with your ${d.hand} ${d.unit}.`
                                    : `Saved - the app said ${d.app}, you measured ${d.hand} ${d.unit} (difference ${d.difference > 0 ? '+' : ''}${d.difference}).`)
                        : (d.error || 'Could not save.');
                } catch (e) { $('hc-status').textContent = 'Could not save - check the connection.'; }
                $('hc-save').disabled = false;
            };
        } else hc.style.display = 'none';
        const next = r.next_test;
        nextUrl = next ? next.url : `/tests?mode=${mode}`;
        $('next-btn').textContent = next ? `Next: ${next.name} →` : 'All tests done - see report →';
        $('next-btn').href = nextUrl;
        el.result.style.display = 'flex';
        $('next-btn').focus();
        say(`Finished. Your result: ${val}. ${b.rating ? 'Rating: ' + b.rating + '.' : ''} ` +
            (next ? `Next test: ${next.name}. Press N to continue.` : 'You have finished all tests.'), true);
        flash(b.met ? 'ok' : 'bad');
    }
    $('retake-btn').addEventListener('click', () => {
        el.result.style.display = 'none';
        el.value.textContent = '0';
        el.start.disabled = !verified;
        say('Ready to retake. Press space to start.', true);
    });

    // ------------------------------------------------------------ photo dialog (dumbbell number / scale display)
    const Snap = (() => {
        let stream = null, done = null, cfg = null;
        const box = $('snap'), video = $('snap-video'), img = $('snap-img'), status = $('snap-status');
        function stopCam() { if (stream) { stream.getTracks().forEach((t) => t.stop()); stream = null; } }
        function close(result) { stopCam(); box.classList.remove('open'); if (done) { const d = done; done = null; d(result); } }
        async function send(blob) {
            status.textContent = 'Reading…'; $('snap-take').disabled = true;
            img.src = URL.createObjectURL(blob); img.style.display = 'block'; video.style.display = 'none'; stopCam();
            const fd = new FormData(); fd.append('photo', blob, 'photo.jpg');
            let res;
            try { res = await (await fetch(cfg.url, { method: 'POST', body: fd })).json(); }
            catch (e) { res = { ok: false, error: 'No connection to the server.' }; }
            $('snap-take').disabled = false;
            if (res.ok) { close(res); return; }
            status.textContent = res.error || 'Could not read it - try again.';
            say(status.textContent, true);
            $('snap-take').textContent = '📸 Try again';
        }
        async function startCam() {
            img.style.display = 'none'; video.style.display = 'block'; $('snap-take').textContent = '📸 Take photo';
            try {
                stream = await navigator.mediaDevices.getUserMedia({ video: { width: { ideal: 1280 }, height: { ideal: 720 }, facingMode: 'environment' } });
                video.srcObject = stream;
            } catch (e) { status.textContent = 'Camera not available here - upload a photo instead.'; video.style.display = 'none'; }
        }
        $('snap-take').addEventListener('click', () => {
            if (!stream) { startCam(); status.textContent = ''; return; }
            const c = document.createElement('canvas'); c.width = video.videoWidth; c.height = video.videoHeight;
            if (!c.width) return;
            c.getContext('2d').drawImage(video, 0, 0);
            c.toBlob((b) => b && send(b), 'image/jpeg', 0.9);
        });
        $('snap-file').addEventListener('change', (e) => { const f = e.target.files[0]; e.target.value = ''; if (f) send(f); });
        $('snap-cancel').addEventListener('click', () => close(null));
        box.addEventListener('keydown', (e) => { if (e.key === 'Escape') close(null); });
        return {
            open(c) {
                cfg = c; $('snap-title').textContent = c.title; $('snap-hint').textContent = c.hint; status.textContent = '';
                box.classList.add('open'); startCam(); $('snap-take').focus(); say(c.title + '. ' + c.hint, true);
                return new Promise((resolve) => { done = resolve; });
            },
        };
    })();

    // ------------------------------------------------------------ dumbbell: detect the weight
    let detected = null;
    function setLoad(kg) {
        $('in-load').value = kg;
        document.querySelectorAll('.load-pick').forEach((x) => x.classList.toggle('on', Number(x.dataset.kg) === Number(kg)));
    }
    if ($('detect-load')) $('detect-load').addEventListener('click', async () => {
        const res = await Snap.open({ title: 'Show your dumbbell', url: '/api/dumbbell/detect',
            hint: 'Hold it close with the end that says "5 KG" (or similar) facing the camera, then take the photo.' });
        if (!res) return;
        detected = { source: res.source, kg: res.kg, label_text: res.label_text || null, model: res.model, sure: res.sure, object: res.object };
        setLoad(res.kg);
        const box = $('load-detected');
        if (res.source === 'label') {
            box.className = 'detected ok';
            box.textContent = `✓ Detected ${res.kg} kg - read "${res.label_text || res.kg + ' kg'}" on the ${res.object || 'dumbbell'}` + (res.model ? ` · ${res.model}` : '');
            say(`Detected ${res.kg} kilograms.`, true);
        } else {
            box.className = 'detected warn';
            box.textContent = `≈ ${res.kg} kg - no number was readable, so this is a guess from its look. Tap the right weight below if it's wrong.`;
            say(`Looks like about ${res.kg} kilograms. Please confirm the weight.`, true);
        }
    });

    // ------------------------------------------------------------ height & weight: read the scale
    let scaleRead = null;
    if ($('read-scale')) $('read-scale').addEventListener('click', async () => {
        const res = await Snap.open({ title: 'Photo of your scale', url: '/api/vision/scale',
            hint: 'Stand on the scale, wait until the number stops changing, then photograph the display (fill the frame, no glare).' });
        if (!res) return;
        scaleRead = { kg: res.kg, reading: res.reading, unit: res.unit, model: res.model, confidence: res.confidence };
        $('in-hw-weight').value = res.kg;
        const box = $('scale-read');
        box.className = 'detected ' + (res.sure ? 'ok' : 'warn');
        box.textContent = (res.sure ? '✓ ' : '') + `Read ${res.reading} ${res.unit} on the display → ${res.kg} kg` +
            (res.sure ? '' : ' - not fully sure, check the number') + (res.model ? ` · ${res.model}` : '');
        say(`Your weight: ${res.kg} kilograms.`, true);
    });

    // ------------------------------------------------------------ dumbbell weight picker
    document.querySelectorAll('.load-pick').forEach((b) => b.addEventListener('click', () => {
        document.querySelectorAll('.load-pick').forEach((x) => x.classList.toggle('on', x === b));
        $('in-load').value = b.dataset.kg;
    }));
    if ($('in-load')) $('in-load').addEventListener('input', () => {
        document.querySelectorAll('.load-pick').forEach((x) => x.classList.toggle('on', Number(x.dataset.kg) === Number($('in-load').value)));
    });

    // ------------------------------------------------------------ wiring
    el.verify.addEventListener('click', verify);
    el.start.addEventListener('click', start);
    el.stop.addEventListener('click', stop);
    el.speak.addEventListener('click', () => {
        if (mode !== 'blind' && synth) { const u = new SpeechSynthesisUtterance(instructionsText()); synth.cancel(); synth.speak(u); }
        else say(instructionsText(), true);
    });
    document.addEventListener('keydown', (e) => {
        if (e.target.tagName === 'INPUT') return;
        const k = e.key.toLowerCase();
        if (k === 'v') { e.preventDefault(); verify(); }
        else if (k === ' ') { e.preventDefault(); running ? stop() : start(); }
        else if (k === 'i') { say(instructionsText(), true); }
        else if (k === 'n' && nextUrl) { window.location.href = nextUrl; }
        else if (k === 'm') { mirrorToggle(); }
    });
    if ($('mirror-btn')) $('mirror-btn').addEventListener('click', () => mirrorToggle());
    // open the camera for identity check right away
    (async () => {
        try {
            el.verifyVideo.srcObject = await navigator.mediaDevices.getUserMedia({ video: true });
        } catch (e) { /* VerifyView.prepare() will retry on click */ }
    })();
    window.addEventListener('pagehide', () => { if (running) navigator.sendBeacon(`/ex/${EX.key}/cleanup`); });
    // Browsers only allow speech after the first key press / tap, so greet blind users then
    if (mode === 'blind') {
        const greet = (e) => {
            document.removeEventListener('keydown', greet, true); document.removeEventListener('pointerdown', greet, true);
            if (!(e.key && ['v', ' ', 'i', 'n', 'm'].includes(e.key.toLowerCase()))) say(instructionsText(), true);
        };
        document.addEventListener('keydown', greet, true); document.addEventListener('pointerdown', greet, true);
        $('mode-note').textContent = notes.blind + ' Press any key to hear the instructions.';
    }
})();
