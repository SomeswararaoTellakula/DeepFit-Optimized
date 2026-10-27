/*
 * DeepFit - the original full-screen Height & Weight page, measured by the shared engine (stature.py).
 *
 *   Verify Face -> Open Exercise -> stand still (it measures by itself after ~5 s)
 *   or say "capture" / press S -> the height and weight are shown and SPOKEN, and saved
 *   -> Submit (F) opens the cumulative results.  R = measure again, Q = quit.
 *
 * With the two DeepFit sheets on the wall the height is measured (about +/-1 cm). Without them it is ESTIMATED
 * from the body's own proportions (about +/-8 cm) and the weight is a typical weight for that height - the
 * screen and the voice say so.
 */
(function () {
    const CFG = Object.assign({ key: 'height_weight', duration: 60, requireFace: true, verifyUrl: '/api/verify_user_identity',
                                resultsUrl: '/performance_dashboard' }, window.CLASSIC || {});
    const KEY = CFG.key;
    const $ = (id) => document.getElementById(id);
    const el = {
        feed: $('videoFeed'), cam: $('webcamPreview'), placeholder: $('placeholder'), info: $('infoPanel'),
        stats: $('statsOverlay'), h: $('heightDisplay'), w: $('weightDisplay'), conf: $('confidenceDisplay'),
        verify: $('verifyFaceBtn'), open: $('openExerciseBtn'), capture: $('saveBtn'), submit: $('submitBtn'), reset: $('resetBtn'),
        badge: $('autoSaveStatus'), result: $('resultPanel'), resH: $('resHeight'), resW: $('resWeight'), resNote: $('resNote'),
        mic: $('micStatus'), line: $('feedbackLine'),
    };
    const notify = (msg, type) => { try { notificationSystem.show(msg, type || 'info'); } catch (e) { } };
    let verified = !CFG.requireFace, running = false, pollTimer = null, result = null, wantSubmit = false, lastFeedback = '';

    // ------------------------------------------------------------ speaking ("tell")
    const synth = window.speechSynthesis;
    function say(text) {
        if (!synth || !text) return;
        try { synth.cancel(); const u = new SpeechSynthesisUtterance(text); u.rate = 1.0; u.lang = 'en-IN'; synth.speak(u); } catch (e) { }
    }

    // ------------------------------------------------------------ listening for "capture"
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    let rec = null, listen = false, lastHeard = 0;
    function micText(t, cls) { el.mic.textContent = t; el.mic.className = 'mic' + (cls ? ' ' + cls : ''); }
    if (!SR) micText('Voice not supported - press S');
    function startListening() {
        if (!SR) return;
        listen = true;
        if (rec) return;
        rec = new SR();
        rec.lang = 'en-IN'; rec.continuous = true; rec.interimResults = true;
        rec.onresult = (e) => {
            for (let i = e.resultIndex; i < e.results.length; i++) {
                const t = e.results[i][0].transcript.toLowerCase();
                if (Date.now() - lastHeard < 2000) continue;
                if (/\b(capture|capcher|kapture|captcha|capture it)\b/.test(t)) { lastHeard = Date.now(); micText('Heard "capture"', 'heard'); doCapture(); }
                else if (/\bsubmit\b/.test(t)) { lastHeard = Date.now(); micText('Heard "submit"', 'heard'); submit(); }
                else if (/\breset\b/.test(t)) { lastHeard = Date.now(); micText('Heard "reset"', 'heard'); reset(); }
            }
        };
        rec.onerror = (e) => {
            if (e.error === 'not-allowed' || e.error === 'service-not-allowed') { listen = false; micText('Microphone blocked - press S'); }
        };
        rec.onend = () => { rec = null; if (listen) setTimeout(startListening, 300); else if (SR) micText('Say "capture"'); };
        try { rec.start(); micText('Listening - say "capture"', 'on'); } catch (e) { }
    }
    function stopListening() { listen = false; if (rec) { try { rec.stop(); } catch (e) { } } }

    // ------------------------------------------------------------ step 1: face check in the video area
    let verifyStream = null;
    async function startVerifyCamera() {
        if (verifyStream || verified) return;
        try {
            verifyStream = await navigator.mediaDevices.getUserMedia({ video: true });
            el.cam.srcObject = verifyStream;
            VerifyView.done = false;
            el.info.style.display = 'none';            // don't cover the live view
            VerifyView.show();
        } catch (e) { notify('Camera access denied: ' + e.message, 'error'); }
    }
    function stopVerifyCamera() {
        if (verifyStream) verifyStream.getTracks().forEach((t) => t.stop());
        verifyStream = null;
    }
    VerifyView.attach({
        container: document.querySelector('.video-wrapper'), video: el.cam,
        onHidden: () => { if (el.feed.style.display !== 'block' && el.result.style.display !== 'block') el.info.style.display = 'block'; },
    });
    if (VerifyView.wrap) {           // keep the status message clear of the button row and the back button
        VerifyView.wrap.querySelector('.vv-status').style.bottom = '95px';
        VerifyView.wrap.querySelector('.vv-tag').style.left = '75px';
        VerifyView.wrap.querySelector('.vv-tag').style.top = '28px';
    }
    if (verified) { el.verify.style.display = 'none'; el.open.style.display = 'inline-block'; }
    else startVerifyCamera();

    el.verify.addEventListener('click', async () => {
        el.verify.disabled = true; el.verify.textContent = 'Verifying...';
        try { await VerifyView.prepare(); } catch (e) { el.verify.disabled = false; el.verify.textContent = 'Verify Face'; return; }
        verifyStream = el.cam.srcObject;
        VerifyView.busy();
        try {
            const r = await (await fetch(CFG.verifyUrl, {
                method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ frame_data: VerifyView.captureFrame() }),
            })).json();
            if (r.success && r.is_match) {
                VerifyView.success();
                stopVerifyCamera();
                verified = true;
                el.verify.style.display = 'none';
                el.open.style.display = 'inline-block';
                say('Identity verified. Press open exercise when you are ready.');
            } else {
                VerifyView.fail(r.message || r.error);
                el.verify.disabled = false; el.verify.textContent = 'Verify Face';
            }
        } catch (e) {
            VerifyView.fail('Could not reach the server');
            el.verify.disabled = false; el.verify.textContent = 'Verify Face';
        }
    });

    // ------------------------------------------------------------ step 2: measure
    function showButtons(measuring) {
        el.capture.style.display = measuring ? 'inline-block' : 'none';
        el.submit.style.display = 'inline-block';
        el.reset.style.display = 'inline-block';
    }
    async function open() {
        if (!verified || running) return;
        el.open.style.display = 'none';
        el.info.style.display = 'none'; el.result.style.display = 'none';
        el.placeholder.style.display = 'flex';
        el.placeholder.innerHTML = '<h3>🚀 Initializing AI...</h3>';
        let res;
        try {
            res = await (await fetch(`/ex/${KEY}/start`, {
                method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ mode: 'standard' }),
            })).json();
        } catch (e) { res = { message: 'Could not reach the server' }; }
        if (!res || res.status !== 'success') {
            notify('Error: ' + ((res && res.message) || 'could not start'), 'error');
            el.placeholder.style.display = 'none';
            el.info.style.display = 'block';
            if (res && res.identity_required) { verified = false; el.verify.style.display = 'inline-block'; el.verify.disabled = false; el.verify.textContent = 'Verify Face'; startVerifyCamera(); }
            else el.open.style.display = 'inline-block';
            return;
        }
        running = true; result = null; wantSubmit = false; lastFeedback = '';
        el.feed.src = `/ex/${KEY}/video_feed?t=${Date.now()}`;
        el.feed.style.display = 'block';
        el.placeholder.style.display = 'none';
        el.stats.style.display = 'flex';
        el.h.textContent = '-- cm'; el.w.textContent = '-- kg'; el.conf.textContent = '0%';
        el.badge.style.display = 'block'; el.badge.textContent = 'Get ready...';
        showButtons(true);
        startListening();
        say('Stand straight and hold still. Say capture when you are ready.');
        pollTimer = setInterval(poll, 500);
    }
    el.open.addEventListener('click', open);

    function fmtCm(v, approx) { return v == null ? '-- cm' : (approx ? '≈ ' : '') + Number(v).toFixed(1) + ' cm'; }
    function fmtKg(v, approx) { return v == null ? '-- kg' : (approx ? '≈ ' : '') + Number(v).toFixed(1) + ' kg'; }

    async function poll() {
        let s;
        try { s = await (await fetch(`/ex/${KEY}/stats`)).json(); } catch (e) { return; }
        if (!s || s.active === undefined || !running) return;
        const L = s.live || {}, cd = Math.ceil(s.countdown || 0);
        if (cd > 0) { el.badge.textContent = `Get ready... ${cd}`; }
        else if (L.need) el.badge.textContent = `Measuring ${Math.min(L.samples || 0, L.need)}/${L.need}`;
        const approx = L.mode !== 'sheets';
        el.h.textContent = fmtCm(L.height_cm, approx);
        el.w.textContent = fmtKg(L.weight_kg, approx && L.weight_estimated);
        el.conf.textContent = (L.confidence || 0) + '%';
        const fb = cd > 0 ? `Get ready... ${cd}` : (s.feedback || '');
        if (fb) { el.line.style.display = 'block'; el.line.textContent = fb; }
        if (fb && fb !== lastFeedback && /step back|closer|face the camera|stand straight|head and feet/i.test(fb)) say(fb);
        lastFeedback = fb;
        if (s.identity_error) {
            endRun();
            alert('A different person was detected. Session stopped - only the registered athlete can be measured.');
            el.open.style.display = 'inline-block';
            return;
        }
        if (s.result) { endRun(); showResult(s.result); }
        else if (!s.active) { endRun(); el.open.style.display = 'inline-block'; el.info.style.display = 'block'; }
    }
    function endRun() {
        running = false;
        clearInterval(pollTimer); pollTimer = null;
        stopListening();
        el.feed.src = ''; el.feed.style.display = 'none';
        el.badge.style.display = 'none'; el.line.style.display = 'none';
        el.capture.style.display = 'none';
    }

    function showResult(r) {
        result = r;
        const M = r.measurement || {}, est = !!(r.estimate || M.estimate);
        if (!r.height_cm) {
            el.result.style.display = 'block';
            el.resH.textContent = '--'; el.resW.textContent = '--';
            el.resNote.textContent = 'Could not measure - ' + (r.feedback || 'stand in full view, head to feet, and hold still') + '.';
            say('I could not measure you. Please stand in full view and try again.');
            showButtons(false);
            return;
        }
        const wEst = r.weight_source === 'estimate';
        el.h.textContent = fmtCm(r.height_cm, est);
        el.w.textContent = fmtKg(r.weight_kg, wEst);
        el.conf.textContent = (M.confidence != null ? M.confidence : (M.stable ? 99 : 0)) + '%';
        el.resH.textContent = (est ? '≈ ' : '') + Math.round(r.height_cm) + ' cm';
        el.resW.textContent = r.weight_kg ? (wEst ? '≈ ' : '') + Math.round(r.weight_kg) + ' kg' : '--';
        el.resNote.textContent = est
            ? `Estimated from your body proportions (usually within about ±${M.uncertainty_cm || 8} cm). The weight is a typical weight for this height - a camera cannot weigh you. For an exact height, put the two DeepFit sheets on the wall.`
            : `Measured with the wall sheets (about ±1 cm).` + (r.bmi ? ` BMI ${r.bmi}${r.bmi_category ? ' - ' + r.bmi_category : ''}.` : '');
        if (r.saved === false) el.resNote.textContent += ' Not saved - the identity check failed.';
        el.result.querySelector('h2').innerHTML = '<i class="fas fa-check-circle" style="color:#4ade80"></i> ' + (est ? 'Estimated' : 'Measured');
        el.result.style.display = 'block';
        showButtons(false);
        const hSay = est ? `about ${Math.round(r.height_cm)} centimetres` : `${r.height_cm} centimetres`;
        const wSay = r.weight_kg ? (wEst ? `, and your weight is about ${Math.round(r.weight_kg)} kilograms` : `, and your weight is ${r.weight_kg} kilograms`) : '';
        say(`Your height is ${hSay}${wSay}.` + (est ? ' These are estimates.' : '') + ' Say submit, or press F, to see all your results.');
        if (wantSubmit) setTimeout(submit, 2500);
    }

    async function doCapture() {
        if (!running) return;
        try {
            const r = await (await fetch(`/ex/${KEY}/capture`, { method: 'POST' })).json();
            if (r && r.ok === false && r.message) { notify(r.message, 'warning'); say(r.message); }
            else { el.badge.textContent = 'Capturing...'; poll(); }
        } catch (e) { notify('Could not reach the server', 'error'); }
    }
    el.capture.addEventListener('click', doCapture);

    async function submit() {
        if (running) { wantSubmit = true; return doCapture(); }       // measure first, then go
        if (!result) { notify('Measure first: press Open Exercise and stand still.', 'warning'); return; }
        if (result.saved === false) { notify('This result was not saved (identity check). Verify and measure again.', 'error'); return; }
        window.location.href = CFG.resultsUrl;
    }
    el.submit.addEventListener('click', submit);

    async function reset() {
        if (running) { try { await fetch(`/ex/${KEY}/abort`, { method: 'POST' }); } catch (e) { } endRun(); }
        result = null;
        el.result.style.display = 'none';
        el.stats.style.display = 'none';
        el.submit.style.display = 'none'; el.reset.style.display = 'none';
        if (verified) open(); else { el.info.style.display = 'block'; el.verify.style.display = 'inline-block'; }
    }
    el.reset.addEventListener('click', reset);

    // ------------------------------------------------------------ keys (as on the original page)
    document.addEventListener('keydown', (e) => {
        if (e.target && /input|textarea/i.test(e.target.tagName)) return;
        const k = e.key.toLowerCase();
        if (k === 's' && running) doCapture();
        else if (k === 'f') submit();
        else if (k === 'r' && (running || result)) reset();
        else if (k === 'q') window.location.href = '/';
        else if ((k === ' ' || k === 'enter') && el.open.style.display !== 'none' && !running) { e.preventDefault(); open(); }
    });
    window.addEventListener('pagehide', () => {
        if (running && navigator.sendBeacon) navigator.sendBeacon(`/ex/${KEY}/abort`);
    });
})();
