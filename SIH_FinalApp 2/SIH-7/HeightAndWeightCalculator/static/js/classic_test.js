/*
 * DeepFit - the original Sit-ups / Dumbbell Curls / Vertical Jump screens, run by the shared test engine.
 *
 * The page keeps its own look. This file only runs the test:
 *   Verify Identity -> Start Camera (3 s countdown) -> live numbers -> time up / Stop Camera -> Submit
 *   -> the cumulative results.
 * Engine calls: /ex/<key>/start, /ex/<key>/video_feed, /ex/<key>/stats, /ex/<key>/stop, /ex/<key>/abort.
 *
 * The page sets window.CLASSIC = { key, duration, requireFace, verifyUrl, resultsUrl } and calls
 * ClassicTest.run({ render(stats), reset(), doneText }).
 */
(function () {
    const $ = (id) => document.getElementById(id);

    const CSS = `
        .popup-overlay { position: fixed; inset: 0; background: rgba(0,0,0,.8); display: flex; align-items: center;
                         justify-content: center; z-index: 1000; }
        .popup-content { background: linear-gradient(135deg, rgba(0,0,0,.9), rgba(0,170,255,.1)); padding: 30px; border-radius: 15px;
                         text-align: center; max-width: 400px; backdrop-filter: blur(10px); border: 1px solid rgba(255,255,255,.1); color: #fff; }
        .popup-content .btn { margin: 6px 4px 0; min-width: 110px; }
        .popup-icon { font-size: 3rem; margin-bottom: 20px; }
        .animate { animation: classic-pop .35s ease-in-out; }
        @keyframes classic-pop { 0% { transform: scale(1); } 50% { transform: scale(1.25); color: #4ade80; } 100% { transform: scale(1); } }
        #video-feed { width: 100%; height: 100%; object-fit: contain; background: #000; }`;

    function run(page) {
        if (!document.getElementById('classic-css')) {
            const st = document.createElement('style'); st.id = 'classic-css'; st.textContent = CSS; document.head.appendChild(st);
        }
        const CFG = window.CLASSIC || {};
        const KEY = CFG.key, DUR = CFG.duration || 60;
        const el = {
            verify: $('verify-btn'), start: $('start-btn'), stop: $('stop-btn'), reset: $('reset-btn'), submit: $('submit-btn'),
            preview: $('preview-btn'), feed: $('video-feed'), previewVideo: $('preview-video'), verifyVideo: $('verify-video'),
            placeholder: $('placeholder'), identity: $('identity-verified'), timer: $('timer-display'),
            timerBar: $('timer-progress'), status: $('session-status'), feedback: $('feedback'),
        };
        let verified = !CFG.requireFace, running = false, pollTimer = null, previewing = false, result = null;
        let popupShown = false, lastEvent = 0;

        // ------------------------------------------------------------ helpers
        function fmt(sec) {
            sec = Math.max(0, Math.ceil(sec));
            return Math.floor(sec / 60) + ':' + String(sec % 60).padStart(2, '0');
        }
        function setTimer(rem) {
            el.timer.textContent = fmt(rem);
            el.timerBar.style.width = Math.min(100, Math.max(0, 100 * (1 - rem / DUR))) + '%';
            el.timer.style.color = rem <= 10 ? '#f44336' : rem <= 30 ? '#ff9800' : '#00d4ff';
        }
        function status(t) { if (el.status) el.status.textContent = t; }
        function identity(text, ok) {
            el.identity.textContent = text;
            el.identity.style.setProperty('color', ok ? '#4CAF50' : '#f44336', 'important');
        }
        function pulse(node) {          // the old screens' little "pop" when a number goes up
            if (!node) return;
            node.classList.remove('animate'); void node.offsetWidth; node.classList.add('animate');
            setTimeout(() => node.classList.remove('animate'), 400);
        }
        function popup(icon, title, text) {
            const p = document.createElement('div');
            p.className = 'popup-overlay';
            p.innerHTML = `<div class="popup-content"><div class="popup-icon"></div><h3></h3><p></p>
                           <button class="btn btn-success">Submit</button> <button class="btn btn-secondary">OK</button></div>`;
            p.querySelector('.popup-icon').textContent = icon;
            p.querySelector('h3').textContent = title;
            p.querySelector('p').textContent = text;
            const [sub, ok] = p.querySelectorAll('button');
            sub.onclick = () => { p.remove(); submit(); };
            ok.onclick = () => p.remove();
            document.body.appendChild(p);
        }
        setTimer(DUR);

        // ------------------------------------------------------------ identity
        function stopVerifyStream() {
            if (el.verifyVideo && el.verifyVideo.srcObject) {
                el.verifyVideo.srcObject.getTracks().forEach((t) => t.stop());
                el.verifyVideo.srcObject = null;
            }
        }
        (async () => {
            if (verified) { identity('Not required', true); el.start.disabled = false; el.start.removeAttribute('title'); return; }
            try {
                el.verifyVideo.srcObject = await navigator.mediaDevices.getUserMedia({ video: true });
                status('Please verify identity to start');
            } catch (e) { status('Allow the camera, then press Verify Identity'); }
        })();
        async function verify() {
            el.verify.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Verifying...';
            el.verify.disabled = true;
            try {
                if (window.VerifyView) { await VerifyView.prepare(); VerifyView.busy(); }
                let frame = window.VerifyView ? VerifyView.captureFrame() : null;
                if (!frame) {
                    const c = document.createElement('canvas');
                    c.width = el.verifyVideo.videoWidth || 640; c.height = el.verifyVideo.videoHeight || 480;
                    c.getContext('2d').drawImage(el.verifyVideo, 0, 0);
                    frame = c.toDataURL('image/jpeg');
                }
                const r = await (await fetch(CFG.verifyUrl, {
                    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ frame_data: frame }),
                })).json();
                if (r.success && r.is_match) {
                    if (window.VerifyView) VerifyView.success();
                    verified = true;
                    el.start.disabled = false; el.start.removeAttribute('title');
                    identity('YES', true);
                    el.verify.innerHTML = '<i class="fas fa-check-circle"></i> Verified';
                    status('Identity verified. Ready to start.');
                    stopVerifyStream();
                } else {
                    identity('NO', false);
                    el.verify.innerHTML = '<i class="fas fa-user-check"></i> Verify Identity';
                    el.verify.disabled = false;
                    const msg = (r && (r.message || r.error)) || 'Identity verification failed. Please try again.';
                    if (window.VerifyView) VerifyView.fail(msg); else alert(msg);
                }
            } catch (e) {
                if (window.VerifyView) VerifyView.fail('Could not reach the server');
                el.verify.innerHTML = '<i class="fas fa-user-check"></i> Verify Identity';
                el.verify.disabled = false;
            }
        }

        // ------------------------------------------------------------ camera preview (browser only, nothing is counted)
        async function togglePreview() {
            if (previewing) return stopPreview();
            if (running) return;
            try {
                if (window.VerifyView) VerifyView.hide();
                el.previewVideo.srcObject = await navigator.mediaDevices.getUserMedia({ video: true });
                el.previewVideo.style.display = 'block'; el.feed.style.display = 'none'; el.placeholder.style.display = 'none';
                previewing = true;
                el.preview.innerHTML = '<i class="fas fa-video-slash"></i> Stop Preview';
                el.preview.classList.add('btn-warning');
                status('Preview active');
            } catch (e) { status('Camera access denied: ' + e.message); }
        }
        function stopPreview() {
            if (el.previewVideo.srcObject) { el.previewVideo.srcObject.getTracks().forEach((t) => t.stop()); el.previewVideo.srcObject = null; }
            el.previewVideo.style.display = 'none';
            if (!running) el.placeholder.style.display = 'flex';
            previewing = false;
            el.preview.innerHTML = '<i class="fas fa-video"></i> Camera Preview';
            el.preview.classList.remove('btn-warning');
            if (!verified && window.VerifyView && el.verifyVideo.srcObject) setTimeout(() => VerifyView.show(), 0);
        }

        // ------------------------------------------------------------ the test
        async function start() {
            if (!verified) { alert('Please verify your identity first.'); return; }
            if (running) return;
            if (previewing) stopPreview();
            if (window.VerifyView && VerifyView.hide) VerifyView.hide();
            stopVerifyStream();                    // the server opens the camera now
            el.start.disabled = true;
            status('Starting AI system...');
            let res;
            try {
                res = await (await fetch(`/ex/${KEY}/start`, {
                    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ mode: 'standard' }),
                })).json();
            } catch (e) { res = { message: 'Could not reach the server' }; }
            if (!res || res.status !== 'success') {
                el.start.disabled = false;
                const msg = (res && res.message) || 'Could not start';
                status(msg);
                if (res && res.identity_required) {
                    verified = false; identity('NO', false);
                    el.verify.disabled = false; el.verify.innerHTML = '<i class="fas fa-user-check"></i> Verify Identity';
                }
                alert(msg);
                return;
            }
            running = true; result = null; popupShown = false; lastEvent = 0;
            page.reset();
            setTimer(DUR);
            el.feed.src = `/ex/${KEY}/video_feed?t=${Date.now()}`;
            el.feed.style.display = 'block'; el.placeholder.style.display = 'none';
            el.stop.disabled = false;
            status('Get ready...');
            pollTimer = setInterval(poll, 400);
        }

        const idText = { verified: 'YES (live)', pending: 'Checking...', no_face: 'Face not visible' };
        async function poll() {
            let s;
            try { s = await (await fetch(`/ex/${KEY}/stats`)).json(); } catch (e) { return; }
            if (!s || s.active === undefined || !running) return;
            const cd = Math.ceil(s.countdown || 0);
            setTimer(cd > 0 || s.remaining == null ? DUR : s.remaining);
            status(s.result ? 'Session complete!' : cd > 0 ? `Get ready... ${cd}` : (s.active ? 'Session in progress' : 'Stopped'));
            if (el.feedback) el.feedback.textContent = cd > 0 ? `Get ready... ${cd}` : (s.feedback || '');
            if (s.identity_status) {
                const bad = s.identity_status === 'mismatch' || s.identity_status === 'face_hidden';
                identity(bad ? `${s.identity_status === 'mismatch' ? 'MISMATCH' : 'Face hidden'} ${s.identity_strikes}/3`
                             : (idText[s.identity_status] || 'YES'), !bad);
            }
            for (const ev of (s.events || [])) {          // a counted rep / jump: make the number pop
                if (ev.id <= lastEvent) continue;
                lastEvent = ev.id;
                if (ev.kind === 'rep' && page.onRep) page.onRep(ev);
            }
            page.render(s, pulse);
            if (s.identity_error) {
                endRun();
                alert('A different person was detected. Test stopped - only the registered athlete can take it.');
                return;
            }
            if (s.result) {
                endRun(); result = s.result;
                if (!popupShown) { popupShown = true; popup('⏰', page.doneTitle || 'Time Completed!', page.doneText || 'Press Submit to see your results.'); }
            } else if (!s.active) endRun();
        }
        function endRun() {
            running = false;
            clearInterval(pollTimer); pollTimer = null;
            el.feed.src = ''; el.feed.style.display = 'none'; el.placeholder.style.display = 'flex';
            el.stop.disabled = true; el.start.disabled = !verified;
        }
        async function stop() {
            if (!running) return;
            el.stop.disabled = true;
            status('Saving...');
            let res = null;
            try { res = await (await fetch(`/ex/${KEY}/stop`, { method: 'POST' })).json(); } catch (e) { }
            try {                                           // the final numbers
                const s = await (await fetch(`/ex/${KEY}/stats`)).json();
                if (s && s.active !== undefined) page.render(s, pulse);
            } catch (e) { }
            endRun();
            if (res && res.result) { result = res.result; status('Stopped - result saved. Press Submit.'); }
            else status('Stopped');
        }
        async function reset() {          // throw this run away (nothing is saved) and start again
            if (running) { try { await fetch(`/ex/${KEY}/abort`, { method: 'POST' }); } catch (e) { } }
            endRun();
            result = null; popupShown = false;
            page.reset(); setTimer(DUR);
            if (el.feedback) el.feedback.textContent = 'Get Ready';
            status(verified ? 'Counter reset! Ready to start.' : 'Please verify identity to start');
        }
        async function submit() {
            if (running) await stop();
            if (!result) { alert('Do the test first: verify your identity, then press Start Camera.'); return; }
            if (result.saved === false) { alert('This result was not saved (identity check). Please verify and try again.'); return; }
            window.location.href = (CFG.resultsUrl || '/dashboard') + (page.resultQuery ? page.resultQuery(result) : '');
        }

        el.verify.addEventListener('click', verify);
        el.start.addEventListener('click', start);
        el.stop.addEventListener('click', stop);
        el.reset.addEventListener('click', reset);
        el.submit.addEventListener('click', submit);
        el.preview.addEventListener('click', togglePreview);
        // leaving the page mid-test throws the run away (Submit saves it)
        window.addEventListener('pagehide', () => {
            if (running && navigator.sendBeacon) navigator.sendBeacon(`/ex/${KEY}/abort`);
        });
    }

    window.ClassicTest = { run };
})();
