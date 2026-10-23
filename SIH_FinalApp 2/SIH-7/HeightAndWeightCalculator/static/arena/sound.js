// DeepFit Arena - sound: effects, spatial cues for blind players, background music and crowd.
// Everything is synthesised with WebAudio (no audio files to download).

const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
let AC = null, master = null, musicBus = null, sfxBus = null, noiseBuf = null;
export const SOUND = { muted: false, music: true };

export function audio() {
  if (!AC) {
    try {
      AC = new (window.AudioContext || window.webkitAudioContext)();
      master = AC.createGain(); master.gain.value = 0.9; master.connect(AC.destination);
      musicBus = AC.createGain(); musicBus.gain.value = 0.32; musicBus.connect(master);
      sfxBus = AC.createGain(); sfxBus.gain.value = 1; sfxBus.connect(master);
      noiseBuf = AC.createBuffer(1, AC.sampleRate, AC.sampleRate);
      const d = noiseBuf.getChannelData(0); for (let i = 0; i < d.length; i++) d[i] = Math.random() * 2 - 1;
    } catch (e) { AC = null; }
  }
  if (AC && AC.state === 'suspended') AC.resume();
  return AC;
}
export function setMuted(m) { SOUND.muted = m; if (master) master.gain.value = m ? 0 : 0.9; }
export function duck(on) { if (musicBus && AC) musicBus.gain.setTargetAtTime(on ? 0.1 : 0.32, AC.currentTime, 0.15); }

export function tone(freq, ms, { pan = 0, vol = 0.18, type = 'sine', slideTo = null, at = 0, bus = null } = {}) {
  const ac = audio(); if (!ac || SOUND.muted) return;
  const o = ac.createOscillator(), g = ac.createGain(), p = ac.createStereoPanner ? ac.createStereoPanner() : null;
  const now = ac.currentTime + at;
  o.type = type; o.frequency.setValueAtTime(freq, now);
  if (slideTo) o.frequency.exponentialRampToValueAtTime(Math.max(20, slideTo), now + ms / 1000);
  g.gain.setValueAtTime(0.0001, now); g.gain.exponentialRampToValueAtTime(vol, now + 0.012); g.gain.exponentialRampToValueAtTime(0.0001, now + ms / 1000);
  o.connect(g); if (p) { p.pan.value = clamp(pan, -1, 1); g.connect(p); p.connect(bus || sfxBus); } else g.connect(bus || sfxBus);
  o.start(now); o.stop(now + ms / 1000 + 0.03);
}
function noise(ms, { vol = 0.2, f = 1200, q = 0.8, type = 'bandpass', at = 0, pan = 0, bus = null, attack = 0.005 } = {}) {
  const ac = audio(); if (!ac || SOUND.muted) return;
  const s = ac.createBufferSource(), bq = ac.createBiquadFilter(), g = ac.createGain(), p = ac.createStereoPanner ? ac.createStereoPanner() : null;
  const now = ac.currentTime + at;
  s.buffer = noiseBuf; bq.type = type; bq.frequency.value = f; bq.Q.value = q;
  g.gain.setValueAtTime(0.0001, now); g.gain.exponentialRampToValueAtTime(vol, now + attack); g.gain.exponentialRampToValueAtTime(0.0001, now + ms / 1000);
  s.connect(bq); bq.connect(g); if (p) { p.pan.value = pan; g.connect(p); p.connect(bus || sfxBus); } else g.connect(bus || sfxBus);
  s.start(now, Math.random() * 0.5); s.stop(now + ms / 1000 + 0.05);
}

export const sfx = {
  ok: () => { tone(880, 110, { type: 'square', vol: 0.08 }); tone(1320, 160, { type: 'square', vol: 0.08, at: 0.09 }); tone(1760, 200, { vol: 0.12, at: 0.18 }); },
  coin: () => { tone(988, 80, { type: 'square', vol: 0.07 }); tone(1319, 260, { type: 'square', vol: 0.07, at: 0.07 }); },
  bad: () => { tone(220, 260, { type: 'sawtooth', vol: 0.09, slideTo: 90 }); noise(200, { vol: 0.15, f: 300 }); },
  thud: () => { tone(120, 220, { vol: 0.35, slideTo: 40 }); noise(150, { vol: 0.2, f: 200, type: 'lowpass' }); },
  tick: (pan = 0) => tone(1000, 60, { pan }),
  whoosh: (pan, ms = 500) => { noise(ms, { vol: 0.35, f: 900, q: 1.4, pan, attack: ms / 2000 }); tone(260, ms, { pan, type: 'triangle', slideTo: 900, vol: 0.12 }); },
  go: () => { tone(523, 120, { type: 'square', vol: 0.09 }); tone(784, 120, { type: 'square', vol: 0.09, at: 0.11 }); tone(1046, 380, { type: 'square', vol: 0.1, at: 0.22 }); },
  count: () => tone(660, 140, { type: 'square', vol: 0.09 }),
  levelUp: () => [523, 659, 784, 1046, 1319].forEach((f, i) => tone(f, 160, { type: 'square', vol: 0.08, at: i * 0.09 })),
  star: (i = 0) => { tone(1046 + i * 220, 140, { type: 'triangle', vol: 0.16 }); tone(1568 + i * 220, 220, { type: 'sine', vol: 0.1, at: 0.06 }); },
  victory: () => [523, 659, 784, 659, 784, 1046].forEach((f, i) => tone(f, i === 5 ? 700 : 170, { type: 'square', vol: 0.09, at: i * 0.16 })),
  cheer: (big = false) => { noise(big ? 2200 : 1100, { vol: big ? 0.3 : 0.18, f: 1600, q: 0.5, attack: 0.25 }); noise(big ? 1800 : 900, { vol: 0.12, f: 3000, q: 0.7, attack: 0.3, at: 0.1 }); },
  lightsOut: () => { tone(180, 380, { type: 'sawtooth', vol: 0.12, slideTo: 60 }); noise(300, { vol: 0.2, f: 120, type: 'lowpass' }); },
  hit: () => { tone(1800, 50, { vol: 0.2 }); noise(90, { vol: 0.25, f: 2500 }); },
  step: () => noise(60, { vol: 0.08, f: 500 }),
};

// ------------------------------------------------------------------ music: a tiny step sequencer per world
const SONGS = {
  // dhol-style kabaddi groove
  kabaddi: { bpm: 112, steps: 16, dha: 'x..x..x.x..x..x.', tin: '..x...x...x..x.x', bass: [43, 0, 0, 43, 0, 0, 46, 0, 41, 0, 0, 41, 0, 0, 43, 0], lead: null },
  title: { bpm: 104, steps: 16, dha: 'x.....x.x.....x.', tin: '....x.......x...', bass: [43, 0, 0, 0, 46, 0, 0, 0, 41, 0, 0, 0, 38, 0, 0, 0], lead: [67, 0, 70, 0, 72, 0, 70, 67, 65, 0, 67, 0, 0, 0, 0, 0] },
  jungle: { bpm: 120, steps: 16, kick: 'x...x...x...x...', hat: '..x...x...x...x.', bass: [36, 0, 36, 0, 39, 0, 39, 0, 41, 0, 41, 0, 39, 0, 39, 0], lead: [72, 0, 0, 74, 0, 0, 76, 0, 79, 0, 0, 76, 0, 74, 0, 0] },
  street: { bpm: 150, steps: 16, kick: 'x.x.x.x.x.x.x.x.', hat: '.x.x.x.x.x.x.x.x', bass: [40, 40, 0, 40, 43, 43, 0, 43, 45, 45, 0, 45, 43, 43, 0, 43], lead: null },
  lab: { bpm: 90, steps: 16, kick: 'x.......x.......', hat: null, bass: [33, 0, 0, 0, 0, 0, 0, 0, 36, 0, 0, 0, 0, 0, 0, 0], lead: [81, 0, 0, 0, 84, 0, 0, 0, 79, 0, 0, 0, 76, 0, 0, 0], pad: true },
  stadium: { bpm: 100, steps: 16, kick: 'x.......x.......', hat: '....x.......x...', bass: [38, 0, 0, 0, 38, 0, 0, 0, 41, 0, 0, 0, 36, 0, 0, 0], lead: null, crowd: true },
  stage: { bpm: 116, steps: 16, kick: 'x...x...x...x...', hat: '..x...x...x...x.', clap: '....x.......x...', bass: [41, 0, 41, 53, 0, 41, 0, 48, 39, 0, 39, 51, 0, 39, 0, 46], lead: [77, 0, 80, 0, 82, 0, 80, 77, 75, 0, 77, 0, 72, 0, 0, 0] },
};
const midi = (n) => 440 * Math.pow(2, (n - 69) / 12);
let seq = null;
export const BEAT = { phase: 0, t0: 0, bpm: 120 };

export function playMusic(world) {
  stopMusic();
  const song = SONGS[world]; const ac = audio();
  if (!song || !ac || !SOUND.music) return;
  const stepDur = 60 / song.bpm / 4;
  let step = 0, next = ac.currentTime + 0.08;
  BEAT.t0 = next; BEAT.bpm = song.bpm;
  const at = (s) => s - ac.currentTime;
  const hit = (pat, i) => pat && pat[i % pat.length] === 'x';
  const id = setInterval(() => {
    if (SOUND.muted) { next = ac.currentTime + 0.05; return; }
    while (next < ac.currentTime + 0.12) {
      const i = step % song.steps, o = at(next);
      if (hit(song.dha, i)) { tone(95, 260, { vol: 0.5, slideTo: 55, at: o, bus: musicBus }); }
      if (hit(song.tin, i)) { tone(420, 90, { vol: 0.22, type: 'triangle', slideTo: 300, at: o, bus: musicBus }); noise(60, { vol: 0.08, f: 3000, at: o, bus: musicBus }); }
      if (hit(song.kick, i)) tone(110, 180, { vol: 0.55, slideTo: 40, at: o, bus: musicBus });
      if (hit(song.hat, i)) noise(40, { vol: 0.08, f: 8000, type: 'highpass', at: o, bus: musicBus });
      if (hit(song.clap, i)) noise(120, { vol: 0.2, f: 1500, at: o, bus: musicBus });
      if (song.bass && song.bass[i]) tone(midi(song.bass[i]), stepDur * 1000 * 1.6, { vol: 0.2, type: 'triangle', at: o, bus: musicBus });
      if (song.lead && song.lead[i]) tone(midi(song.lead[i]), stepDur * 1000 * 1.4, { vol: 0.06, type: 'square', at: o, bus: musicBus });
      if (song.pad && i === 0) [57, 60, 64].forEach((n) => tone(midi(n), stepDur * 16000, { vol: 0.03, type: 'sine', at: o, bus: musicBus }));
      if (song.crowd && i % 8 === 0) noise(stepDur * 8000, { vol: 0.05, f: 1400, q: 0.4, at: o, attack: 0.4, bus: musicBus });
      next += stepDur; step++;
    }
  }, 25);
  seq = { id, world };
}
export function stopMusic() { if (seq) { clearInterval(seq.id); seq = null; } }
/** 0..1 pulse on every beat (for lights that flash with the music). */
export function beatPulse() {
  if (!AC || !seq) return 0;
  const beats = (AC.currentTime - BEAT.t0) * BEAT.bpm / 60;
  return Math.max(0, 1 - (beats - Math.floor(beats)) * 3);
}
