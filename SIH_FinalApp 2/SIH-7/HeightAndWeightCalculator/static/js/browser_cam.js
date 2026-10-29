/*
 * DeepFitCam - where the test video comes from.
 *
 *   Laptop running the server itself (localhost): the server opens its own webcam and streams
 *   /ex/<key>/video_feed (unchanged).
 *   Hosted server (Render) or a phone on the LAN: the server has no webcam, so this browser opens
 *   its camera and sends each frame to /ex/<key>/frame. The server runs the same test on it (identity
 *   re-check, pose, counting) and sends the frame back with the skeleton drawn - shown in the same <img>.
 *
 *   const cam = DeepFitCam.source();                  // put in the /start request body as "source"
 *   const feed = await DeepFitCam.attach(key, imgEl, startResponse, onError);
 *   feed.stop();
 */
(function () {
    const LOCAL = ['localhost', '127.0.0.1', '::1', '[::1]'];

    function source() {
        return LOCAL.includes(location.hostname) ? 'auto' : 'browser';
    }

    async function attach(key, img, res, onError) {
        if (!res || res.source !== 'browser') {
            img.src = `/ex/${key}/video_feed?t=${Date.now()}`;
            return { stop() { img.removeAttribute('src'); } };
        }
        const [W, H] = res.frame_size || [640, 480];
        let stream;
        try {
            stream = await navigator.mediaDevices.getUserMedia({
                video: { width: { ideal: W }, height: { ideal: H }, facingMode: 'user' }, audio: false,
            });
        } catch (e) {
            if (onError) onError('Camera access was blocked. Allow the camera for this site (padlock icon in the address bar) and press Start again.');
            return { stop() { } };
        }
        const video = document.createElement('video');
        video.muted = true; video.playsInline = true; video.srcObject = stream;
        try { await video.play(); } catch (e) { }
        const canvas = document.createElement('canvas');
        let active = true, lastUrl = null;

        async function loop() {
            while (active) {
                if (!video.videoWidth) { await new Promise((r) => setTimeout(r, 100)); continue; }
                const scale = Math.min(1, W / video.videoWidth, H / video.videoHeight);
                canvas.width = Math.round(video.videoWidth * scale);
                canvas.height = Math.round(video.videoHeight * scale);
                canvas.getContext('2d').drawImage(video, 0, 0, canvas.width, canvas.height);
                const blob = await new Promise((r) => canvas.toBlob(r, 'image/jpeg', 0.7));
                if (!blob || !active) break;
                let r;
                try {
                    r = await fetch(`/ex/${key}/frame`, { method: 'POST', body: blob, headers: { 'Content-Type': 'image/jpeg' } });
                } catch (e) { await new Promise((ok) => setTimeout(ok, 500)); continue; }   // network hiccup: try again
                if (r.status === 204) break;                                           // test over
                if (!r.ok) { await new Promise((ok) => setTimeout(ok, 300)); continue; }
                const out = await r.blob();
                if (!active) break;
                const url = URL.createObjectURL(out);
                img.src = url;
                if (lastUrl) URL.revokeObjectURL(lastUrl);
                lastUrl = url;
                if (r.headers.get('X-Test-Done') === '1') break;
            }
            stopStream();
        }
        function stopStream() {
            stream.getTracks().forEach((t) => t.stop());
        }
        loop();
        return {
            stop() {
                active = false; stopStream();
                img.removeAttribute('src');
                if (lastUrl) { URL.revokeObjectURL(lastUrl); lastUrl = null; }
            },
        };
    }

    window.DeepFitCam = { source, attach };
})();
