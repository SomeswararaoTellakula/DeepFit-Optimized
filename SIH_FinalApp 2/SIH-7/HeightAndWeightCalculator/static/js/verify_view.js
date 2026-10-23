/*
 * VerifyView - shows the live webcam inside the main exercise video area
 * while the athlete verifies their identity, with a face guide and a status
 * message (verifying / verified / not matched).
 *
 * Usage (done automatically for pages that have #verify-video and .video-container):
 *   VerifyView.attach({ container, video })
 *   VerifyView.busy()            -> "Verifying..."
 *   VerifyView.success()         -> green tick on a frozen frame, then hides
 *   VerifyView.fail(message)     -> red message, live view stays on
 *   VerifyView.hide() / show()
 */
(function () {
    const STYLE = `
    .vv-wrap { position:absolute; inset:0; z-index:5; display:none; overflow:hidden;
               border-radius:inherit; background:#000; }
    .vv-wrap video, .vv-wrap canvas { width:100%; height:100%; object-fit:cover;
               transform:scaleX(-1); display:block; }
    .vv-wrap canvas { position:absolute; inset:0; display:none; }
    .vv-guide { position:absolute; left:50%; top:46%; width:34%; aspect-ratio:3/4;
               transform:translate(-50%,-50%); border:3px dashed rgba(255,255,255,.75);
               border-radius:50%; box-shadow:0 0 0 9999px rgba(0,0,0,.28);
               transition:border-color .25s, box-shadow .25s; pointer-events:none; }
    .vv-wrap.vv-ok   .vv-guide { border:4px solid #22c55e; box-shadow:0 0 0 9999px rgba(0,0,0,.35); }
    .vv-wrap.vv-fail .vv-guide { border:4px solid #ef4444; }
    .vv-wrap.vv-busy .vv-guide { border-color:#38bdf8; animation:vv-pulse 1s infinite; }
    @keyframes vv-pulse { 50% { border-color:rgba(56,189,248,.35); } }
    .vv-status { position:absolute; left:50%; bottom:6%; transform:translateX(-50%);
               max-width:90%; padding:10px 18px; border-radius:999px; font:600 15px/1.3 system-ui,sans-serif;
               color:#fff; background:rgba(15,23,42,.85); text-align:center; white-space:normal; }
    .vv-wrap.vv-ok   .vv-status { background:rgba(22,163,74,.92); }
    .vv-wrap.vv-fail .vv-status { background:rgba(220,38,38,.92); }
    .vv-tag { position:absolute; top:12px; left:12px; padding:4px 10px; border-radius:6px;
               font:600 12px system-ui,sans-serif; color:#fff; background:rgba(0,0,0,.55); }
    .vv-tag::before { content:''; display:inline-block; width:8px; height:8px; margin-right:6px;
               border-radius:50%; background:#ef4444; vertical-align:middle; }
    `;

    const VV = {
        wrap: null, video: null, canvas: null, status: null, onHidden: null,

        attach(opts) {
            if (this.wrap) return this;
            const container = opts.container;
            const video = opts.video;
            if (!container || !video) return this;

            if (!document.getElementById('vv-style')) {
                const s = document.createElement('style');
                s.id = 'vv-style';
                s.textContent = STYLE;
                document.head.appendChild(s);
            }
            if (getComputedStyle(container).position === 'static') container.style.position = 'relative';

            this.wrap = document.createElement('div');
            this.wrap.className = 'vv-wrap';
            this.wrap.innerHTML = '<div class="vv-tag">LIVE · Identity check</div>' +
                '<div class="vv-guide"></div><div class="vv-status"></div>';
            this.canvas = document.createElement('canvas');
            this.wrap.insertBefore(this.canvas, this.wrap.firstChild);
            video.removeAttribute('style');
            this.wrap.insertBefore(video, this.wrap.firstChild);
            container.appendChild(this.wrap);

            this.video = video;
            this.status = this.wrap.querySelector('.vv-status');
            this.onHidden = opts.onHidden || null;

            // Show as soon as the webcam stream is playing
            const ready = () => { if (!this.done) this.show(); };
            video.addEventListener('loadedmetadata', ready);
            if (video.srcObject && video.readyState >= 1) ready();
            this.setStatus('Look at the camera, keep your face inside the oval, then click "Verify Identity"');
            return this;
        },

        setStatus(text, kind) {
            if (!this.wrap) return;
            this.wrap.classList.remove('vv-ok', 'vv-fail', 'vv-busy');
            if (kind) this.wrap.classList.add('vv-' + kind);
            this.status.textContent = text;
        },

        show() {
            if (!this.wrap) return;
            this.canvas.style.display = 'none';
            this.wrap.style.display = 'block';
            const ph = document.getElementById('placeholder');
            if (ph) ph.style.display = 'none';
        },

        hide() {
            if (!this.wrap) return;
            this.wrap.style.display = 'none';
            if (this.onHidden) this.onHidden();
        },

        isVisible() { return !!this.wrap && this.wrap.style.display === 'block'; },

        // Frame for the server (not mirrored)
        captureFrame() {
            const v = this.video;
            const c = document.createElement('canvas');
            c.width = v.videoWidth || 640;
            c.height = v.videoHeight || 480;
            c.getContext('2d').drawImage(v, 0, 0, c.width, c.height);
            return c.toDataURL('image/jpeg', 0.92);
        },

        // Wait until the webcam is delivering real frames (the first frames after
        // opening the camera are often black, which caused "no face" on the first try)
        async ready(timeoutMs) {
            const v = this.video;
            const until = Date.now() + (timeoutMs || 3000);
            while (Date.now() < until) {
                if (v && v.readyState >= 2 && v.videoWidth > 0 && v.currentTime > 0.5) return true;
                await new Promise(r => setTimeout(r, 100));
            }
            return false;
        },

        // Called when "Verify" is clicked: make sure the live camera is open and
        // showing in the exercise area, give the athlete a moment to see themselves,
        // then the caller captures the frame.
        async prepare() {
            if (!this.wrap) return;
            const v = this.video;
            const live = v.srcObject && v.srcObject.getTracks().some(t => t.readyState === 'live');
            const wasVisible = this.isVisible() && !this.done;
            this.done = false;
            if (!live) {
                try {
                    v.srcObject = await navigator.mediaDevices.getUserMedia({ video: true });
                    await v.play().catch(() => {});
                } catch (e) {
                    this.show();
                    this.setStatus('Camera blocked - allow camera access in the browser and try again', 'fail');
                    throw e;
                }
            }
            this.show();
            await this.ready();
            if (!wasVisible) {
                // first time the athlete sees the preview: short countdown
                for (const n of [3, 2, 1]) {
                    this.setStatus(`Look at the camera… ${n}`, 'busy');
                    await new Promise(r => setTimeout(r, 700));
                }
            }
        },

        busy() {
            this.show();
            this.setStatus('Verifying your face…', 'busy');
        },

        fail(message) {
            this.show();
            this.setStatus((message || 'Face did not match') + ' - adjust and try again', 'fail');
        },

        success(message) {
            if (!this.wrap) return;
            this.done = true;
            // Freeze the last frame so it stays visible after the camera stops
            const v = this.video;
            this.canvas.width = v.videoWidth || 640;
            this.canvas.height = v.videoHeight || 480;
            try { this.canvas.getContext('2d').drawImage(v, 0, 0, this.canvas.width, this.canvas.height); } catch (e) {}
            this.canvas.style.display = 'block';
            this.setStatus(message || '✓ Identity verified - you can start the exercise', 'ok');
            setTimeout(() => this.hide(), 1800);
        }
    };

    window.VerifyView = VV;

    // Auto-attach on the standard exercise pages (sit-ups, dumbbell, vertical jump)
    document.addEventListener('DOMContentLoaded', () => {
        const video = document.getElementById('verify-video');
        const feedEl = document.getElementById('video-feed');
        const container = (feedEl && feedEl.parentElement) || document.querySelector('.video-container');
        if (video && container) {
            VV.attach({
                container, video,
                onHidden: () => {
                    const ph = document.getElementById('placeholder');
                    const feed = document.getElementById('video-feed');
                    const prev = document.getElementById('preview-video');
                    const busy = (feed && feed.style.display === 'block') || (prev && prev.style.display === 'block');
                    if (ph && !busy) {
                        ph.style.display = 'flex';
                        const p = ph.querySelector('p');
                        const h = ph.querySelector('h3');
                        if (h) h.textContent = '✅ Identity verified';
                        if (p) p.textContent = 'Press "Start" to begin';
                    }
                }
            });
        }
    });
})();
