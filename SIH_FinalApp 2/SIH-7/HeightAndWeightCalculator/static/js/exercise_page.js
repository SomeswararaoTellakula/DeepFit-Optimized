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
