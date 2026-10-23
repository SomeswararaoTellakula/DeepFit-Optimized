// DeepFit Arena - "the game IS the trial".
//
// A full-body camera game. The player is cut out of their room and dropped into each level's
// world (MediaPipe Pose + segmentation, running in the browser - the video never leaves the
// device). Six levels, each secretly a sports-science test:
//   Raider Dodge  (kabaddi court)    -> reflexes + agility
//   Log Jump      (jungle track)     -> leg power
//   Bull Run      (village street)   -> raises the heart rate
//   Heart Scan    (x2, camera PPG)   -> heart-rate recovery
//   Read the Bowler (night stadium)  -> anticipation (occlusion test: the floodlights go out)
//   Dance-off     (disco stage)      -> learning speed
// Upper-body mode: when only the waist up is in view (laptop, phone propped close) the game plays
// Shadow Boxing, Heart Scan, Read the Bowler (by leaning), Dance-off and the final scan, then
// offers the full-body levels as a bonus. Traits it could not measure are "not measured", not zero.
// The server recomputes every score AND the game points from the raw measurements
// (arena_score.py), so the leaderboard can't be faked by editing this file.

import * as ART from './art.js?v=2';
import { sfx, tone, audio, playMusic, stopMusic, setMuted, duck, beatPulse, SOUND } from './sound.js?v=2';
import { LandmarkFilter, classifyMove, MoveTracker, PunchDetector } from './motion.js?v=2';

const CFG = JSON.parse(document.getElementById('arena-cfg').textContent);
const Q = new URLSearchParams(location.search);
const FAST = Q.get('fast') === '1';                 // short pauses (automated tests)
const $ = (id) => document.getElementById(id);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
const rand = (a, b) => a + Math.random() * (b - a);
const median = (a) => { if (!a.length) return null; const s = [...a].sort((x, y) => x - y); const m = s.length >> 1; return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2; };
const CANVAS_FONT = '"Bungee", "Baloo Tammudu 2", "Baloo 2", system-ui, sans-serif';

const MP_VERSION = '0.10.14';
const MP_BASE = `https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@${MP_VERSION}`;
// Pose model: "full" is clearly more accurate than "lite" and still real-time on ordinary laptops and phones.
// If this device is too slow for it (> ~55 ms a frame), the game switches to "lite" by itself. ?model=lite|full|heavy forces one.
const MP_MODEL_URL = (m) => `https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_${m}/float16/1/pose_landmarker_${m}.task`;
let MP_MODEL_NAME = ['lite', 'full', 'heavy'].includes(Q.get('model')) ? Q.get('model') : 'full';

// ------------------------------------------------------------------ text in three languages
const I18N = {
  en: {
    calib: 'Step back until your whole body is in the frame, then stand still.',
    calib_auto: 'Step back so your whole body is in the frame for all levels - or stay where you are for the upper-body game.',
    calib_upper: 'Keep your head, shoulders and arms in the frame, then stay still.',
    upper_mode: 'UPPER-BODY GAME! Your legs are not in view, so we play the upper-body levels.',
    feet_hint: 'Step back - this level needs your feet in the picture.',
    hands_in_view: 'Move back a little, so your raised hands stay in the picture.',
    sees: 'I see',
    step_back_upper: 'Now sit back so your head, shoulders and arms are in the frame.',
    boxing_intro: 'Shadow Boxing! Fists up by your chin. When a pad lights up, punch towards the screen with that hand - then bring the fist back.',
    pow: 'POW!',
    bonus_title: 'UNLOCK 3 BONUS LEVELS?', bonus_text: 'Raider Dodge, Log Jump and Bull Run measure reflexes, agility and power. They need your whole body in view - step back from the camera.',
    bonus_yes: 'Yes - play the bonus levels', bonus_no: 'Show my results',
    bonus_say: 'Great run! Want 3 bonus levels? They need your whole body in view. Say yes, or say results.',
    scope_upper: 'Measured: upper body', scope_full: 'Measured: full body', not_measured: 'not measured',
    calib_ok: 'Ready!',
    dodge_intro: 'Raider Dodge! When a raider charges from one side, step quickly to the other side.',
    center: 'Come back to the middle.',
    dodged: 'DODGED!', tagged: 'TAGGED!', raider: 'Raider!',
    jump_intro: 'Log Jump! Jump when the log reaches your feet.', jump_now: 'JUMP!', cleared: 'CLEARED!', hit: 'BONK!',
    escape_intro: 'Bull Run! A bull is chasing you. Run on the spot as fast as you can!',
    pulse_intro: 'Heart Scan! Come close to the camera, keep your face in the ring and stay very still.',
    pulse_measuring: 'Scanning your heart. Stay still.', pulse_back: 'Come back into the ring.',
    step_back: 'Now step back so your whole body is visible again.',
    bowler_intro: "Read the Bowler! Watch the bowler's body. The floodlights go off before you see the ball. Step to the side where the ball will go.",
    bowler_blind_intro: 'Read the ball by sound! Listen to the throw. The sound stops early. Step to the side where the ball is going.',
    where: 'Where will it go? Step left or right!', correct: 'CORRECT!', wrong: 'MISSED IT!',
    combo_intro: 'Dance-off! Watch the dancer, remember the moves, then do them in order.',
    combo_go: 'Your turn!', perfect: 'PERFECT!', good: 'GOOD!',
    try_tip: (n, e, k, mv) => `Try ${n}: ${e} mistakes. Remember step ${k}: ${mv}.`,
    results: 'Game over! Here is your score and your hidden talent profile.', left: 'left', right: 'right',
    level: 'LEVEL', clear: 'LEVEL CLEAR!', escaped: 'ESCAPED!', phew: 'PHEW! CLOSE ONE!', lights: 'LIGHTS OUT!', heart_ok: 'HEART SCANNED!',
    titles: { dodge: 'RAIDER DODGE', jump: 'LOG JUMP', escape: 'BULL RUN', pulse: 'HEART SCAN', bowler: 'READ THE BOWLER', combo: 'DANCE-OFF', boxing: 'SHADOW BOXING' },
    measures: { boxing: 'Gets your heart pumping', dodge: 'Secretly measures: reflexes + agility', jump: 'Secretly measures: leg power', escape: 'Gets your heart pumping',
                pulse: 'Secretly measures: heart recovery', bowler: 'Secretly measures: game reading', combo: 'Secretly measures: learning speed' },
  },
  hi: {
    calib: 'पीछे हटिए ताकि आपका पूरा शरीर फ्रेम में दिखे, फिर स्थिर खड़े रहिए।',
    calib_auto: 'सारे लेवल के लिए पीछे हटिए ताकि पूरा शरीर दिखे - या जहाँ हैं वहीं रहिए, ऊपरी शरीर वाले खेल के लिए।',
    calib_upper: 'सिर, कंधे और हाथ फ्रेम में रखिए, फिर स्थिर रहिए।',
    upper_mode: 'ऊपरी शरीर का खेल! आपके पैर नहीं दिख रहे, इसलिए हम ऊपरी शरीर वाले लेवल खेलेंगे।',
    feet_hint: 'पीछे हटिए - इस लेवल में पैर दिखने चाहिए।',
    hands_in_view: 'थोड़ा पीछे हटिए, ताकि ऊपर उठे हाथ तस्वीर में रहें।',
    sees: 'दिख रहा है',
    step_back_upper: 'अब पीछे बैठिए ताकि सिर, कंधे और हाथ फ्रेम में दिखें।',
    boxing_intro: 'शैडो बॉक्सिंग! मुट्ठियाँ ठोड़ी के पास रखो। जिस तरफ़ पैड जले, उस हाथ से स्क्रीन की ओर मुक्का मारो - फिर मुट्ठी वापस लाओ।',
    pow: 'धमाक!',
    bonus_title: '3 बोनस लेवल खोलें?', bonus_text: 'रेडर से बचो, लकड़ी कूदो और सांड दौड़ - प्रतिक्रिया, फुर्ती और ताकत मापते हैं। इनमें पूरा शरीर दिखना चाहिए - कैमरे से पीछे हटिए।',
    bonus_yes: 'हाँ - बोनस लेवल खेलो', bonus_no: 'मेरे नतीजे दिखाओ',
    bonus_say: 'शानदार खेल! 3 बोनस लेवल खेलना चाहोगे? इनमें पूरा शरीर दिखना चाहिए। हाँ बोलो, या नतीजे बोलो।',
    scope_upper: 'मापा गया: ऊपरी शरीर', scope_full: 'मापा गया: पूरा शरीर', not_measured: 'मापा नहीं गया',
    calib_ok: 'तैयार!',
    dodge_intro: 'रेडर से बचो! जब रेडर एक तरफ से आए, तुरंत दूसरी तरफ कदम रखो।',
    center: 'बीच में वापस आओ।',
    dodged: 'बच गए!', tagged: 'पकड़े गए!', raider: 'रेडर!',
    jump_intro: 'लकड़ी कूदो! जब लकड़ी आपके पैरों तक पहुँचे, तब कूदो।', jump_now: 'कूदो!', cleared: 'बढ़िया!', hit: 'धप्प!',
    escape_intro: 'सांड दौड़! सांड पीछे आ रहा है। अपनी जगह पर जितना तेज़ हो सके दौड़ो!',
    pulse_intro: 'हार्ट स्कैन! कैमरे के पास आइए, चेहरा घेरे में रखिए और बिल्कुल स्थिर रहिए।',
    pulse_measuring: 'दिल की जाँच हो रही है। स्थिर रहिए।', pulse_back: 'घेरे में वापस आइए।',
    step_back: 'अब पीछे हटिए ताकि पूरा शरीर फिर से दिखे।',
    bowler_intro: 'गेंदबाज़ को पढ़ो! गेंदबाज़ के शरीर को ध्यान से देखो। गेंद दिखने से पहले लाइटें बुझ जाएँगी। उस तरफ कदम रखो जहाँ गेंद जाएगी।',
    bowler_blind_intro: 'आवाज़ से गेंद पढ़ो! फेंकने की आवाज़ सुनो। आवाज़ जल्दी रुक जाएगी। उस तरफ कदम रखो जहाँ गेंद जा रही है।',
    where: 'गेंद किधर जाएगी? बाएँ या दाएँ कदम रखो!', correct: 'सही!', wrong: 'चूक गए!',
    combo_intro: 'डांस मुकाबला! डांसर को देखो, चालें याद रखो, फिर उसी क्रम में करो।',
    combo_go: 'अब तुम्हारी बारी!', perfect: 'परफेक्ट!', good: 'बढ़िया!',
    try_tip: (n, e, k, mv) => `प्रयास ${n}: ${e} गलतियाँ। कदम ${k} याद रखो: ${mv}।`,
    results: 'खेल खत्म! यह रहा आपका स्कोर और आपकी छुपी प्रतिभा।', left: 'बाएँ', right: 'दाएँ',
    level: 'लेवल', clear: 'लेवल पूरा!', escaped: 'बच निकले!', phew: 'बाल-बाल बचे!', lights: 'लाइटें बंद!', heart_ok: 'दिल की जाँच पूरी!',
    titles: { dodge: 'रेडर से बचो', jump: 'लकड़ी कूदो', escape: 'सांड दौड़', pulse: 'हार्ट स्कैन', bowler: 'गेंदबाज़ को पढ़ो', combo: 'डांस मुकाबला', boxing: 'शैडो बॉक्सिंग' },
    measures: { boxing: 'दिल की धड़कन बढ़ाता है', dodge: 'छुपा माप: प्रतिक्रिया + फुर्ती', jump: 'छुपा माप: पैरों की ताकत', escape: 'दिल की धड़कन बढ़ाता है',
                pulse: 'छुपा माप: दिल की रिकवरी', bowler: 'छुपा माप: खेल की समझ', combo: 'छुपा माप: सीखने की गति' },
  },
  te: {
    calib: 'మీ శరీరం మొత్తం ఫ్రేమ్‌లో కనిపించేలా వెనక్కి వెళ్లి, కదలకుండా నిలబడండి.',
    calib_auto: 'అన్ని లెవెల్స్ కోసం శరీరం మొత్తం కనిపించేలా వెనక్కి వెళ్లండి - లేదా పై శరీర ఆట కోసం అక్కడే ఉండండి.',
    calib_upper: 'తల, భుజాలు, చేతులు ఫ్రేమ్‌లో ఉంచి కదలకుండా ఉండండి.',
    upper_mode: 'పై శరీర ఆట! మీ కాళ్లు కనిపించడం లేదు, కాబట్టి పై శరీర లెవెల్స్ ఆడుదాం.',
    feet_hint: 'వెనక్కి వెళ్లండి - ఈ లెవెల్‌కు మీ పాదాలు కనిపించాలి.',
    hands_in_view: 'కొంచెం వెనక్కి వెళ్లండి, పైకెత్తిన చేతులు చిత్రంలో ఉండాలి.',
    sees: 'కనిపిస్తోంది',
    step_back_upper: 'ఇప్పుడు తల, భుజాలు, చేతులు ఫ్రేమ్‌లో కనిపించేలా వెనక్కి కూర్చోండి.',
    boxing_intro: 'షాడో బాక్సింగ్! పిడికిళ్లు గడ్డం దగ్గర ఉంచండి. ఏ వైపు ప్యాడ్ వెలిగితే ఆ చేత్తో స్క్రీన్ వైపు గుద్దండి - తర్వాత పిడికిలి వెనక్కి తీసుకోండి.',
    pow: 'ఢాం!',
    bonus_title: '3 బోనస్ లెవెల్స్ తెరవాలా?', bonus_text: 'రైడర్ తప్పించుకో, దుంగ దూకు, ఎద్దు పరుగు - ప్రతిస్పందన, చురుకుదనం, శక్తిని కొలుస్తాయి. వీటికి శరీరం మొత్తం కనిపించాలి - కెమెరా నుండి వెనక్కి వెళ్లండి.',
    bonus_yes: 'అవును - బోనస్ లెవెల్స్ ఆడతా', bonus_no: 'నా ఫలితాలు చూపించు',
    bonus_say: 'అద్భుతం! 3 బోనస్ లెవెల్స్ ఆడతారా? వీటికి శరీరం మొత్తం కనిపించాలి. అవును అనండి, లేదా ఫలితాలు అనండి.',
    scope_upper: 'కొలిచింది: పై శరీరం', scope_full: 'కొలిచింది: పూర్తి శరీరం', not_measured: 'కొలవలేదు',
    calib_ok: 'సిద్ధం!',
    dodge_intro: 'రైడర్‌ని తప్పించుకోండి! ఒక వైపు నుండి రైడర్ వస్తే, వెంటనే మరో వైపుకు అడుగు వేయండి.',
    center: 'మధ్యలోకి తిరిగి రండి.',
    dodged: 'తప్పించుకున్నారు!', tagged: 'దొరికిపోయారు!', raider: 'రైడర్!',
    jump_intro: 'దుంగ దూకండి! దుంగ మీ పాదాల దగ్గరికి రాగానే దూకండి.', jump_now: 'దూకండి!', cleared: 'భలే!', hit: 'ఢాం!',
    escape_intro: 'ఎద్దు పరుగు! ఎద్దు వెంటపడుతోంది. ఉన్నచోటే వీలైనంత వేగంగా పరుగెత్తండి!',
    pulse_intro: 'హార్ట్ స్కాన్! కెమెరా దగ్గరకు రండి, ముఖాన్ని వలయంలో ఉంచి కదలకుండా ఉండండి.',
    pulse_measuring: 'మీ గుండెను స్కాన్ చేస్తున్నాం. కదలకండి.', pulse_back: 'వలయంలోకి తిరిగి రండి.',
    step_back: 'ఇప్పుడు మీ శరీరం మొత్తం మళ్లీ కనిపించేలా వెనక్కి వెళ్లండి.',
    bowler_intro: 'బౌలర్‌ను చదవండి! బౌలర్ శరీరాన్ని గమనించండి. బంతి కనిపించేలోపే లైట్లు ఆరిపోతాయి. బంతి వెళ్లే వైపుకు అడుగు వేయండి.',
    bowler_blind_intro: 'శబ్దంతో బంతిని చదవండి! విసిరే శబ్దం వినండి. శబ్దం త్వరగా ఆగిపోతుంది. బంతి వెళ్తున్న వైపుకు అడుగు వేయండి.',
    where: 'బంతి ఎటు వెళ్తుంది? ఎడమకో కుడికో అడుగు వేయండి!', correct: 'సరైనది!', wrong: 'మిస్ అయ్యింది!',
    combo_intro: 'డాన్స్ పోటీ! డాన్సర్‌ను చూసి, కదలికలు గుర్తుపెట్టుకుని, అదే క్రమంలో చేయండి.',
    combo_go: 'ఇప్పుడు మీ వంతు!', perfect: 'పర్ఫెక్ట్!', good: 'బాగుంది!',
    try_tip: (n, e, k, mv) => `ప్రయత్నం ${n}: ${e} తప్పులు. అడుగు ${k} గుర్తుంచుకోండి: ${mv}.`,
    results: 'ఆట ముగిసింది! ఇదిగో మీ స్కోరు మరియు మీ దాగి ఉన్న ప్రతిభ.', left: 'ఎడమ', right: 'కుడి',
    level: 'లెవెల్', clear: 'లెవెల్ పూర్తి!', escaped: 'తప్పించుకున్నారు!', phew: 'తృటిలో తప్పింది!', lights: 'లైట్లు ఆరిపోయాయి!', heart_ok: 'గుండె పరీక్ష పూర్తి!',
    titles: { dodge: 'రైడర్ తప్పించుకో', jump: 'దుంగ దూకు', escape: 'ఎద్దు పరుగు', pulse: 'హార్ట్ స్కాన్', bowler: 'బౌలర్‌ను చదువు', combo: 'డాన్స్ పోటీ', boxing: 'షాడో బాక్సింగ్' },
    measures: { boxing: 'గుండె వేగాన్ని పెంచుతుంది', dodge: 'రహస్య కొలత: ప్రతిస్పందన + చురుకుదనం', jump: 'రహస్య కొలత: కాళ్ల శక్తి', escape: 'గుండె వేగాన్ని పెంచుతుంది',
                pulse: 'రహస్య కొలత: గుండె కోలుకోవడం', bowler: 'రహస్య కొలత: ఆట అవగాహన', combo: 'రహస్య కొలత: నేర్చుకునే వేగం' },
  },
};
const MOVE_TEXT = {
  hands_up: { en: 'Both hands up', hi: 'दोनों हाथ ऊपर', te: 'రెండు చేతులు పైకి', icon: '🙌' },
  left_hand_up: { en: 'Left hand up', hi: 'बायाँ हाथ ऊपर', te: 'ఎడమ చేయి పైకి', icon: '🫲' },
  right_hand_up: { en: 'Right hand up', hi: 'दायाँ हाथ ऊपर', te: 'కుడి చేయి పైకి', icon: '🫱' },
  arms_out: { en: 'Arms out to the sides', hi: 'हाथ दोनों तरफ़ फैलाओ', te: 'చేతులు రెండు వైపులా చాపండి', icon: '🤸' },
  hands_on_head: { en: 'Hands on head', hi: 'हाथ सिर पर', te: 'చేతులు తలపై', icon: '🙆' },
  hands_on_hips: { en: 'Hands on hips', hi: 'हाथ कमर पर', te: 'చేతులు నడుముపై', icon: '🧍' },
  squat: { en: 'Squat down', hi: 'बैठक लगाओ', te: 'కూర్చోండి (స్క్వాట్)', icon: '🏋️' },
};
const LEVEL_META = {
  dodge: { world: 'kabaddi', icon: '🤼', music: 'kabaddi' }, jump: { world: 'jungle', icon: '🪵', music: 'jungle' },
  escape: { world: 'street', icon: '🐂', music: 'street' }, pulse: { world: 'lab', icon: '❤️', music: 'lab' },
  bowler: { world: 'stadium', icon: '🏏', music: 'stadium' }, combo: { world: 'stage', icon: '💃', music: 'stage' },
  boxing: { world: 'kabaddi', icon: '🥊', music: 'kabaddi' },
};
const FULL_BODY_LEVELS = ['dodge', 'jump', 'escape'];

// ------------------------------------------------------------------ state
const S = {
  lang: CFG.lang || 'en', mode: 'standard', quick: true, sim: !!CFG.sim, view: 'camera',
  src: null, vw: 640, vh: 480, lm: null, body: null, base: null, lmRaw: null, bodyRaw: null,
  calib: { method: 'pose', cm_per_px: null, body_px: null },
  level: null, running: false, started: false, lastSay: '', quit: false,
  scope: null,                                   // 'full' | 'upper' - decided by what the camera sees at the start
  raw: { dodge: [], jump: [], escape: null, pulse: [], bowler: [], combo: null, boxing: null },
  plan: Object.assign({}, CFG.plan || {}), profile: null, coach: null, saved: null, serverPoints: null,
  ai: { sam: null, voice: null, spark: null, image: null },
  world: 'title', points: 0, streak: 0, levelPts: {}, stars: {}, dots: [], dotsN: 0,
  excite: 0, scroll: 0, dark: 0, maskOk: false, maskT: 0, lastNow: 0, levelNo: 0,
  light: { luma: null, gain: 1, avatar: false, poorSince: null, goodSince: null },
};
try {
  const saved = JSON.parse(localStorage.getItem('arena_next_plan') || 'null');
  if (saved && !CFG.loggedIn) S.plan = Object.assign(S.plan, saved);
} catch (e) { /* storage blocked */ }
const T = (k) => (I18N[S.lang] && I18N[S.lang][k]) || I18N.en[k];
const moveText = (m) => (MOVE_TEXT[m] ? MOVE_TEXT[m][S.lang] || MOVE_TEXT[m].en : m);

// ------------------------------------------------------------------ voice out (TTS), captions, flashes
let VOICES = [];
function loadVoices() { try { VOICES = speechSynthesis.getVoices() || []; } catch (e) { VOICES = []; } }
if ('speechSynthesis' in window) { loadVoices(); speechSynthesis.onvoiceschanged = loadVoices; }
function voiceFor(lang) {
  const code = { en: 'en', hi: 'hi', te: 'te' }[lang];
  return VOICES.find((v) => v.lang && v.lang.toLowerCase().startsWith(code + '-in')) ||
         VOICES.find((v) => v.lang && v.lang.toLowerCase().startsWith(code));
}
function caption(text) { $('caption').textContent = text || ''; }
function flash(kind) {
  const f = $('flash'); f.className = kind;
  setTimeout(() => { f.className = ''; }, kind === 'ok' ? 300 : 650);
  if (navigator.vibrate && S.mode !== 'standard') navigator.vibrate(kind === 'ok' ? 60 : [60, 60, 60]);
}
/** Speak (unless deaf mode / muted) and caption. Resolves when done, or after a time based on the text length. */
function say(text, { interrupt = true, wait = true } = {}) {
  caption(text); S.lastSay = text;
  const est = FAST ? 250 : clamp(text.length * 55, 900, 9000);
  if (S.mode === 'deaf' || SOUND.muted || !('speechSynthesis' in window)) return wait ? sleep(est) : Promise.resolve();
  return new Promise((resolve) => {
    let done = false; const fin = () => { if (!done) { done = true; duck(false); resolve(); } };
    try {
      if (interrupt) speechSynthesis.cancel();
      const u = new SpeechSynthesisUtterance(text);
      const v = voiceFor(S.lang); if (v) u.voice = v;
      u.lang = { en: 'en-IN', hi: 'hi-IN', te: 'te-IN' }[S.lang]; u.rate = 1.0;
      u.onend = fin; u.onerror = fin;
      duck(true); speechSynthesis.speak(u);
    } catch (e) { fin(); }
    setTimeout(fin, wait ? est + (FAST ? 0 : 1500) : 0);
  });
}

// ------------------------------------------------------------------ landmarks -> body measurements
// lm: 33 x {x, y, v}, normalised, UN-mirrored (as the camera sees). Game logic works in
// mirrored screen pixels so "move to the left of the screen" = "move to your own left".
function bodyInfo(lm) {
  const P = (i) => ({ x: (1 - lm[i].x) * S.vw, y: lm[i].y * S.vh, v: lm[i].v });
  const ls = P(11), rs = P(12), lh = P(23), rh = P(24), la = P(27), ra = P(28), nose = P(0), le = P(2), re = P(5);
  const lk = P(25), rk = P(26);
  const ank = (la.y + ra.y) / 2;
  return {
    hipX: (lh.x + rh.x) / 2, hipY: (lh.y + rh.y) / 2, shX: (ls.x + rs.x) / 2, shY: (ls.y + rs.y) / 2,
    sw: Math.max(8, Math.abs(ls.x - rs.x)), nose, ankY: ank, bodyPx: ank - nose.y, lk, rk,
    full: [0, 23, 24, 27, 28].every((i) => lm[i].v >= 0.5),
    upper: [0, 11, 12].every((i) => lm[i].v >= 0.5),          // head + shoulders (hips may be behind a desk)
    face: [0, 2, 5].every((i) => lm[i].v >= 0.5), eyeDist: Math.hypot(le.x - re.x, le.y - re.y),
  };
}
// Dance moves are read by motion.js (classifyMove + MoveTracker): smoothed points, a held and settled pose.
function editDistance(a, b) {
  const dp = Array.from({ length: a.length + 1 }, (_, i) => [i, ...Array(b.length).fill(0)]);
  for (let j = 0; j <= b.length; j++) dp[0][j] = j;
  for (let i = 1; i <= a.length; i++) for (let j = 1; j <= b.length; j++)
    dp[i][j] = Math.min(dp[i - 1][j] + 1, dp[i][j - 1] + 1, dp[i - 1][j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
  // first wrong / missing step, for the tip
  let firstBad = null;
  for (let k = 0; k < a.length; k++) if (b[k] !== a[k]) { firstBad = k; break; }
  return { dist: dp[a.length][b.length], firstBad };
}

// ------------------------------------------------------------------ pulse from the face (remote PPG, POS method)
class PulseMeter {
  constructor() { this.s = []; }
  add(t, rgb) { this.s.push([t, rgb[0], rgb[1], rgb[2]]); }
  get seconds() { return this.s.length < 2 ? 0 : (this.s[this.s.length - 1][0] - this.s[0][0]) / 1000; }
  estimate(winSec = 12) {
    const s = this.s; if (s.length < 30) return null;
    const fs = 30, end = s[s.length - 1][0], start = Math.max(s[0][0], end - winSec * 1000);
    const n = Math.floor((end - start) / 1000 * fs); if (n < fs * 6) return null;
    const R = new Float64Array(n), G = new Float64Array(n), B = new Float64Array(n);
    let j = 0;
    for (let i = 0; i < n; i++) {           // resample to an even 30 Hz
      const t = start + i * 1000 / fs;
      while (j < s.length - 2 && s[j + 1][0] < t) j++;
      const a = s[j], b = s[j + 1] || a, w = b[0] === a[0] ? 0 : clamp((t - a[0]) / (b[0] - a[0]), 0, 1);
      R[i] = a[1] + w * (b[1] - a[1]); G[i] = a[2] + w * (b[2] - a[2]); B[i] = a[3] + w * (b[3] - a[3]);
    }
    const l = Math.round(1.6 * fs), H = new Float64Array(n);
    const mean = (arr, a, b) => { let m = 0; for (let i = a; i < b; i++) m += arr[i]; return m / (b - a); };
    for (let m = 0; m + l <= n; m++) {      // POS (Wang et al. 2017)
      const mr = mean(R, m, m + l), mg = mean(G, m, m + l), mb = mean(B, m, m + l);
      if (!mr || !mg || !mb) continue;
      const s1 = new Float64Array(l), s2 = new Float64Array(l);
      for (let k = 0; k < l; k++) { const r = R[m + k] / mr, g = G[m + k] / mg, b = B[m + k] / mb; s1[k] = g - b; s2[k] = g + b - 2 * r; }
      const sd = (x) => { const mu = mean(x, 0, l); let v = 0; for (let k = 0; k < l; k++) v += (x[k] - mu) ** 2; return Math.sqrt(v / l); };
      const a = sd(s2) > 1e-9 ? sd(s1) / sd(s2) : 0;
      const h = new Float64Array(l); let hm = 0;
      for (let k = 0; k < l; k++) { h[k] = s1[k] + a * s2[k]; hm += h[k]; }
      hm /= l;
      for (let k = 0; k < l; k++) H[m + k] += h[k] - hm;
    }
    const half = Math.round(fs / 2), X = new Float64Array(n);   // remove slow drift (1 s moving average)
    for (let i = 0; i < n; i++) { let a = 0, c = 0; for (let k = Math.max(0, i - half); k < Math.min(n, i + half); k++) { a += H[k]; c++; } X[i] = H[i] - a / c; }
    for (let i = 0; i < n; i++) X[i] *= 0.5 - 0.5 * Math.cos(2 * Math.PI * i / (n - 1));   // Hann window
    let best = 0, bestF = 0, total = 0; const pw = [];
    for (let f = 0.7; f <= 3.0001; f += 0.01) {                // 42 - 180 bpm
      let re = 0, im = 0;
      for (let i = 0; i < n; i++) { const ph = 2 * Math.PI * f * i / fs; re += X[i] * Math.cos(ph); im -= X[i] * Math.sin(ph); }
      const p = re * re + im * im; pw.push([f, p]); total += p;
      if (p > best) { best = p; bestF = f; }
    }
    if (!total) return null;
    const near = pw.filter(([f]) => Math.abs(f - bestF) <= 0.1).reduce((a, [, p]) => a + p, 0);
    return { bpm: Math.round(bestF * 60), quality: +(near / total).toFixed(2) };
  }
}
const SAMPLE = document.createElement('canvas');
const SCTX = SAMPLE.getContext('2d', { willReadFrequently: true });
function roiMean(rects) {
  const W = 320, H = Math.round(320 * S.vh / S.vw);
  if (SAMPLE.width !== W) { SAMPLE.width = W; SAMPLE.height = H; }
  SCTX.clearRect(0, 0, W, H); SCTX.drawImage(S.src, 0, 0, W, H);
  let r = 0, g = 0, b = 0, n = 0;
  for (const q of rects) {
    const x0 = clamp(Math.floor(q.x * W), 0, W - 1), y0 = clamp(Math.floor(q.y * H), 0, H - 1);
    const w = clamp(Math.floor(q.w * W), 1, W - x0), h = clamp(Math.floor(q.h * H), 1, H - y0);
    const d = SCTX.getImageData(x0, y0, w, h).data;
    for (let i = 0; i < d.length; i += 4) { r += d[i]; g += d[i + 1]; b += d[i + 2]; n++; }
  }
  return n ? [r / n, g / n, b / n] : null;
}
// forehead + both cheeks from the eye landmarks (normalised, un-mirrored)
function skinRects(lm, samRect) {
  const le = lm[2], re = lm[5];
  const ed = Math.hypot((le.x - re.x) * S.vw, (le.y - re.y) * S.vh) / S.vw, edY = ed * S.vw / S.vh;
  const mx = (le.x + re.x) / 2, my = (le.y + re.y) / 2;
  if (samRect) return [{ x: mx + samRect.dx * ed, y: my + samRect.dy * edY, w: samRect.w * ed, h: samRect.h * edY }];
  return [
    { x: mx - 0.55 * ed, y: my - 0.78 * edY, w: 1.1 * ed, h: 0.45 * edY },
    { x: le.x - 0.22 * ed, y: le.y + 0.62 * edY, w: 0.45 * ed, h: 0.35 * edY },
    { x: re.x - 0.22 * ed, y: re.y + 0.62 * edY, w: 0.45 * ed, h: 0.35 * edY },
  ];
}

// ------------------------------------------------------------------ frame grab (for SAM 3.1)
function grabJpeg(maxW = 640) {
  const c = document.createElement('canvas'); const w = Math.min(maxW, S.vw); c.width = w; c.height = Math.round(w * S.vh / S.vw);
  c.getContext('2d').drawImage(S.src, 0, 0, c.width, c.height);
  return { url: c.toDataURL('image/jpeg', 0.82), w: c.width, h: c.height };
}
async function samBoxes(prompt, timeoutMs = 9000) {
  if (!CFG.metaAvailable || S.sim) return null;
  const img = grabJpeg();
  try {
    const ctl = new AbortController(); const to = setTimeout(() => ctl.abort(), timeoutMs);
    const r = await fetch('/api/arena/sam', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                                              body: JSON.stringify({ image: img.url, prompt }), signal: ctl.signal });
    clearTimeout(to);
    const d = await r.json();
    if (!d.ok || !d.boxes || !d.boxes.length) { S.ai.sam = 'no'; return null; }
    S.ai.sam = 'yes';
    // boxes are in the JPEG's pixels -> normalised
    return d.boxes.map((b) => ({ x1: b.x1 / (b.w || img.w), y1: b.y1 / (b.h || img.h), x2: b.x2 / (b.w || img.w), y2: b.y2 / (b.h || img.h), c: b.c }));
  } catch (e) { S.ai.sam = 'no'; return null; }
}


// ------------------------------------------------------------------ game points (same rules as arena_score.points on the server)
const mult = (s) => Math.min(1 + 0.5 * s, 2.5);
const pyRound = (x) => { const r = Math.round(x); return Math.abs(x - Math.trunc(x)) === 0.5 && r % 2 !== 0 ? r - 1 : r; };   // Python's round()
const BOWL_MULT = { easy: 1, medium: 1.5, hard: 2 };
const LEVEL_WEIGHT = { easy: 1, medium: 2, hard: 3 };
function pointsFor(raw) {
  const lv = {};
  const num = (v, lo, hi) => (typeof v === 'number' && isFinite(v) && v >= lo && v <= hi ? v : null);
  const stars = (r, hi = 0.9, mid = 0.6) => (r == null ? 0 : r >= hi ? 3 : r >= mid ? 2 : 1);
  if (raw.boxing) {
    const secs = num(raw.boxing.secs, 1, 120) || 20, hits = num(raw.boxing.hits, 0, 1000) || 0;
    lv.boxing = { points: pyRound(50 * Math.min(hits, 3 * secs)), max: pyRound(150 * secs), stars: hits / secs >= 2 ? 3 : hits / secs >= 1.2 ? 2 : 1 };
  }
  const d = (raw.dodge || []).slice(0, 30);
  if (d.length) {
    let pts = 0, st = 0, mx = 0;
    d.forEach((t, i) => { mx += 256 * mult(i); if (t.ok) { const rt = num(t.rt, 120, 2000); pts += (100 + (rt ? Math.max(0, (900 - rt) / 5) : 0)) * mult(st); st++; } else st = 0; });
    lv.dodge = { points: pyRound(pts), max: pyRound(mx), stars: stars(d.filter((t) => t.ok).length / d.length) };
  }
  const j = (raw.jump || []).slice(0, 20);
  if (j.length) {
    let pts = 0;
    for (const t of j) if (t.ok) { const cm = num(t.cm, 0, 120) || 0, tm = num(t.timing, -2000, 2000); pts += 100 + 3 * Math.min(cm, 60) + (tm != null && Math.abs(tm) <= 100 ? 50 : tm != null && Math.abs(tm) <= 200 ? 20 : 0); }
    lv.jump = { points: pyRound(pts), max: 330 * j.length, stars: stars(j.filter((t) => t.ok).length / j.length) };
  }
  if (raw.escape) {
    const secs = num(raw.escape.secs, 1, 120) || 10, steps = num(raw.escape.steps, 0, 1000) || 0;
    lv.escape = { points: pyRound(5 * Math.min(steps, 4 * secs)), max: pyRound(20 * secs), stars: steps / secs >= 3.5 ? 3 : steps / secs >= 2.5 ? 2 : 1 };
  }
  const ps = (raw.pulse || []).slice(0, 4);
  if (ps.length) {
    const ok = ps.map((p) => !!num(p.bpm, 40, 210) && (num(p.quality, 0, 1) || 0) >= 0.25);
    lv.pulse = { points: ok.reduce((a, o) => a + (o ? 150 : 50), 0), max: 150 * ps.length, stars: stars(ok.filter(Boolean).length / ok.length, 0.99, 0.5) };
  }
  const b = (raw.bowler || []).filter((t) => BOWL_MULT[t.level]).slice(0, 30);
  if (b.length) {
    let pts = 0, st = 0, best = 0, w = 0, hit = 0;
    b.forEach((t, i) => {
      best += 150 * BOWL_MULT[t.level] * mult(i); w += LEVEL_WEIGHT[t.level];
      if ((t.answer === 'L' || t.answer === 'R') && t.answer === t.target) { pts += 150 * BOWL_MULT[t.level] * mult(st); st++; hit += LEVEL_WEIGHT[t.level]; } else st = 0;
    });
    lv.bowler = { points: pyRound(pts), max: pyRound(best), stars: stars(hit / w, 0.8, 0.6) };
  }
  const c = raw.combo;
  if (c && c.pattern && c.pattern.length && c.tries && c.tries.length) {
    let pts = 0, last = null;
    for (const t of c.tries) { const e = editDistance(c.pattern, t.done || []).dist; pts += 50 * Math.max(0, c.pattern.length - e) + (e === 0 ? 300 : 0); last = e; }
    lv.combo = { points: pts, max: c.tries.length * (50 * c.pattern.length + 300), stars: last === 0 ? 3 : last <= 1 ? 2 : 1 };
  }
  const total = Object.values(lv).reduce((a, v) => a + v.points, 0), max = Object.values(lv).reduce((a, v) => a + v.max, 0) || 1;
  const r = total / max, rank = r >= 0.75 ? ['Legend', '👑'] : r >= 0.55 ? ['Pro', '🔥'] : r >= 0.35 ? ['Rising Star', '⭐'] : ['Rookie', '🌱'];
  const scope = FULL_BODY_LEVELS.some((k) => (Array.isArray(raw[k]) ? raw[k].length : raw[k])) ? 'full' : 'upper';
  return { total, max, percent: pyRound(100 * r), levels: lv, stars: Object.values(lv).reduce((a, v) => a + v.stars, 0), max_stars: 3 * Object.keys(lv).length, rank: rank[0], rank_icon: rank[1], scope };
}

// ------------------------------------------------------------------ screen mapping + HUD helpers
let DPR = 1;
const VIEW = { ox: 0, oy: 0, s: 1, W: 1, H: 1 };
const V = (x, y) => ({ x: VIEW.ox + x * VIEW.s, y: VIEW.oy + y * VIEW.s });
Object.defineProperty(V, 's', { get: () => VIEW.s });
const lmScreen = (lm, i) => V((1 - lm[i].x) * S.vw, lm[i].y * S.vh);
function headPoint() {
  if (S.body) return V(S.body.shX, S.body.shY + (S.base ? S.base.bodyPx : 200) * 0.06);
  return { x: VIEW.W / 2, y: VIEW.H * 0.3 };
}
function award(pts, at, label, color = '#fde047') {
  pts = Math.round(pts);
  S.points += pts; updateScore(pts > 0);
  if (at && label) ART.floatText(at.x, at.y - 40 * DPR, label, { color, size: 56 * DPR });
  if (at && pts > 0) ART.floatText(at.x, at.y + 22 * DPR, '+' + pts, { color: '#fff', size: 40 * DPR, stroke: '#14532d', life: 1.3 });
  if (pts > 0) sfx.coin();
}
function updateScore(bump) {
  $('score-num').textContent = Math.round(S.points).toLocaleString('en-IN');
  if (bump) { const e = $('score'); e.classList.remove('bump'); void e.offsetWidth; e.classList.add('bump'); }
}
function setCombo(streak) {
  if (streak >= 1) { $('combo').hidden = false; $('combo-num').textContent = String(mult(streak)); } else $('combo').hidden = true;
}
function setDots(n, extra = '') {
  S.dotsN = n;
  const d = Array.from({ length: n }, (_, i) => `<span class="dot ${S.dots[i] || (i === S.dots.length ? 'now' : '')}"></span>`).join('');
  $('hud-trial').innerHTML = d + (extra ? ` <span>${extra}</span>` : '');
}
function markDot(ok) { S.dots.push(ok ? 'ok' : 'bad'); setDots(S.dotsN); }
function textTrial(t) { $('hud-trial').textContent = t; }
function success(ok) { if (ok) { S.excite = 1; ART.burst(headPoint().x, headPoint().y, { n: 26, size: 9 * DPR, speed: 420 * DPR, gravity: 900 * DPR }); } else { ART.shake(18 * DPR); } }
function drawArrow(g, x, y, dir, size, color = '#22c55e') {
  g.save(); g.translate(x, y); g.scale(dir, 1);
  g.fillStyle = color; g.strokeStyle = '#14532d'; g.lineWidth = size * 0.08; g.lineJoin = 'round';
  g.beginPath(); g.moveTo(-size * 0.5, -size * 0.18); g.lineTo(0, -size * 0.18); g.lineTo(0, -size * 0.42); g.lineTo(size * 0.55, 0);
  g.lineTo(0, size * 0.42); g.lineTo(0, size * 0.18); g.lineTo(-size * 0.5, size * 0.18); g.closePath(); g.fill(); g.stroke();
  g.restore();
}
function bigText(g, text, x, y, size, color = '#fff', stroke = '#1e1b4b') {
  g.save(); g.font = `${Math.round(size)}px ${CANVAS_FONT}`; g.textAlign = 'center'; g.textBaseline = 'middle';
  g.lineJoin = 'round'; g.lineWidth = Math.max(4, size * 0.14); g.strokeStyle = stroke; g.strokeText(text, x, y); g.fillStyle = color; g.fillText(text, x, y); g.restore();
}

// ------------------------------------------------------------------ levels
class Level {
  constructor(key) { this.key = key; this._fin = false; this.promise = new Promise((r) => { this._res = r; }); }
  finish(v) { if (!this._fin) { this._fin = true; this._res(v); } }
  start() {} update() {} draw() {} drawBack() {}
}
async function play(level) {
  if (level.key !== 'calib') caption('');
  S.level = level; if (level.start) level.start(performance.now());
  const out = await level.promise; S.level = null; return out;
}
// the world's ground line on screen: under the feet in the full-body game; low in the scene in the upper-body game
// (the player is a foreground figure there, cut off at the waist)
const groundLine = () => (S.scope === 'upper' ? VIEW.H * 0.86 : V(0, S.base.ankY).y);
// where the player is, sideways: the hips in the full-body game, the shoulders in the upper-body game
const posX = (b) => (S.scope === 'upper' ? b.shX : b.hipX);
function centered(b) { return b && Math.abs(posX(b) - S.base.hipX) < 0.35 * S.base.sw; }

class Calibrate extends Level {
  // kind: 'auto' (first one: whole body -> full game, only the waist up for a while -> upper-body game),
  //       'full' (bonus levels need the whole body), 'upper' (keep the head, shoulders and arms in view)
  constructor(kind = 'auto', giveUpMs = 0) { super('calib'); this.kind = kind; this.giveUp = giveUpMs; this.hist = []; this.nag = 0; this.prog = 0; this.upSince = null; }
  get text() { return T(this.kind === 'auto' ? 'calib_auto' : this.kind === 'upper' ? 'calib_upper' : 'calib'); }
  start(now) { this.t0 = now; say(this.text, { wait: false }); $('hud-level').textContent = T('calib_ok').replace('!', '') + '…'; textTrial(''); }
  update(now) {
    if (this.giveUp && now - this.t0 > this.giveUp) return this.finish(false);   // couldn't step back: go to the results
    const b = S.body;
    const fullOk = b && b.full && b.bodyPx >= 0.35 * S.vh;
    // upper-body game: head and shoulders steady, legs not in view, for 4 s (time to step back if they want the full game)
    const upOk = b && b.upper && !b.full && b.sw >= 0.12 * S.vw;
    if (this.kind === 'upper' || (this.kind === 'auto' && !fullOk)) {
      if (upOk && (this.kind === 'upper' || now - this.t0 > 2500)) { this.upSince = this.upSince || now; } else this.upSince = null;
      const need = this.kind === 'upper' ? 1300 : 4000;
      this.prog = this.upSince ? clamp((now - this.upSince) / need, 0, 1) : 0;
      if (this.upSince && now - this.upSince >= need) return this.done(now, 'upper');
      if (!upOk && !fullOk && now - this.nag > 6000) { this.nag = now; say(this.text, { wait: false }); }
      if (this.kind === 'upper') return;
    }
    if (!fullOk) { this.hist = []; if (this.kind === 'full' && now - this.nag > 6000) { this.nag = now; say(this.text, { wait: false }); } return; }
    this.upSince = null;
    this.hist.push({ t: now, x: b.hipX, y: b.hipY, sw: b.sw, bp: b.bodyPx, ank: b.ankY });
    this.hist = this.hist.filter((h) => now - h.t < 1500);
    this.prog = clamp((now - this.hist[0].t) / 1300, 0, 1);
    if (this.hist.length < 15 || now - this.hist[0].t < 1300) return;
    const xs = this.hist.map((h) => h.x), ys = this.hist.map((h) => h.y);
    if (Math.max(...xs) - Math.min(...xs) > 0.04 * b.bodyPx || Math.max(...ys) - Math.min(...ys) > 0.03 * b.bodyPx) { this.hist = this.hist.slice(-3); return; }
    S.base = { hipX: median(xs), hipY: median(ys), sw: median(this.hist.map((h) => h.sw)), bodyPx: median(this.hist.map((h) => h.bp)),
               ankY: median(this.hist.map((h) => h.ank)) };
    S.calib = { method: 'pose', cm_per_px: (CFG.heightCm * 0.88) / S.base.bodyPx, body_px: Math.round(S.base.bodyPx) };
    // SAM 3.1: the whole person, head to feet -> exact pixels per cm (pose has no point on top of the head)
    samBoxes('person').then((boxes) => {
      if (!boxes) return;
      const bx = boxes.find((q) => (q.x1 + q.x2) / 2 > 0.15 && (q.x1 + q.x2) / 2 < 0.85) || boxes[0];
      const hPx = (bx.y2 - bx.y1) * S.vh, ratio = hPx / S.base.bodyPx;
      if (ratio > 1.05 && ratio < 1.4) S.calib = { method: 'sam-3.1', cm_per_px: CFG.heightCm / hPx, body_px: Math.round(S.base.bodyPx), sam_height_px: Math.round(hPx) };
    });
    this.done(now, 'full');
  }
  done(now, scope) {
    if (scope === 'upper') {
      const b = S.body;
      // no legs in view: the "ground" is the bottom of the picture and the torso is ~1.5 shoulder widths long
      S.base = { hipX: b.shX, hipY: b.shY + 1.5 * b.sw, sw: b.sw, bodyPx: 2.2 * (b.shY + 1.5 * b.sw - b.nose.y), ankY: S.vh * 0.98 };
    }
    if (this.kind === 'auto') {
      S.scope = scope;
      if (scope === 'upper') { ART.floatText(VIEW.W / 2, VIEW.H * 0.3, '🙋 ' + (S.lang === 'en' ? 'UPPER-BODY GAME' : T('scope_upper')), { color: '#22d3ee', size: 46 * DPR, life: 2.2 }); say(T('upper_mode'), { wait: false }); }
    } else if (this.kind === 'full') S.scope = 'full';
    sfx.ok(); this.finish(true);
  }
  draw(g, V_, now) {
    const a = V(S.vw * 0.27, S.vh * 0.03), b = V(S.vw * 0.73, S.vh * 0.98), L = 40 * DPR;
    g.save(); g.strokeStyle = this.prog > 0 ? '#22c55e' : '#fde047'; g.lineWidth = 8 * DPR; g.lineCap = 'round';
    g.shadowColor = g.strokeStyle; g.shadowBlur = 16;
    for (const [x, y, dx, dy] of [[a.x, a.y, 1, 1], [b.x, a.y, -1, 1], [a.x, b.y, 1, -1], [b.x, b.y, -1, -1]]) {
      g.beginPath(); g.moveTo(x + dx * L, y); g.lineTo(x, y); g.lineTo(x, y + dy * L); g.stroke();
    }
    g.restore();
    const c = V(S.vw / 2, S.vh * 0.16);
    if (this.prog > 0) {
      g.save(); g.strokeStyle = '#22c55e'; g.lineWidth = 10 * DPR; g.beginPath(); g.arc(c.x, c.y, 34 * DPR, -Math.PI / 2, -Math.PI / 2 + this.prog * Math.PI * 2); g.stroke(); g.restore();
      bigText(g, 'READY?', c.x, c.y + 70 * DPR, 40 * DPR, '#fde047');
    } else bigText(g, '⬅  ➡', c.x, c.y, 40 * DPR, '#fff');
  }
}

class Dodge extends Level {
  constructor(n, windowMs) { super('dodge'); this.n = n; this.win = windowMs; this.i = 0; this.state = 'center'; this.tc = null; this.nag = 0; }
  start() { this.state = 'center'; S.dots = []; setDots(this.n); }
  update(now) {
    const b = S.body;
    if (this.state === 'center') {
      if (centered(b)) { this.tc = this.tc || now; if (now - this.tc > 400) { this.state = 'wait'; this.tGo = now + rand(600, 1500); } }
      else { this.tc = null; if (now - this.nag > 4000) { this.nag = now; caption(T('center')); } }
      if (b && centered(b)) S.base.hipX = S.base.hipX * 0.95 + b.hipX * 0.05;   // follow slow drift
    } else if (this.state === 'wait') {
      if (now >= this.tGo) {
        this.side = Math.random() < 0.5 ? 'L' : 'R'; this.t0 = now; this.state = 'cue';
        this.onset = null; this.pend = null; this.peak = 0; this.lastX = b ? b.hipX : null; this.lastT = now;
        sfx.whoosh(this.side === 'L' ? -1 : 1, 450);
        if (S.mode === 'blind') say(T('raider'), { wait: false });
        SIM && SIM.cue('dodge', { side: this.side, now });
      }
    } else if (this.state === 'cue') {
      const safe = this.side === 'L' ? 1 : -1;
      if (b) {
        const d = b.hipX - S.base.hipX, dt = (now - this.lastT) / 1000;
        if (dt > 0 && this.lastX != null) this.peak = Math.max(this.peak, ((b.hipX - this.lastX) / dt / S.base.sw) * safe);
        this.lastX = b.hipX; this.lastT = now;
        // reaction time from the RAW points (no smoothing lag), counted only if the next frame agrees (no jitter blips)
        const rb = S.bodyRaw, dr = rb ? rb.hipX - S.base.hipX : 0;
        if (!this.onset && rb) {
          if (Math.abs(dr) > 0.25 * S.base.sw) {
            if (this.pend && this.pend.dir === Math.sign(dr)) this.onset = this.pend; else this.pend = { rt: now - this.t0, dir: Math.sign(dr) };
          } else this.pend = null;
        }
        if (d * safe > 0.8 * S.base.sw) return this.resolve(true, now);
      }
      if (now - this.t0 > this.win) this.resolve(false, now);
    } else if (this.state === 'feedback' && now > this.tNext) {
      this.i++; if (this.i >= this.n) return this.finish(true);
      this.state = 'center'; this.tc = null;
    }
  }
  resolve(ok, now) {
    const safe = this.side === 'L' ? 1 : -1;
    const t = { side: this.side, ok, rt: this.onset ? Math.round(this.onset.rt) : null, wrong_first: this.onset ? this.onset.dir !== safe : false, peak_v: +this.peak.toFixed(2) };
    S.raw.dodge.push(t);
    this.ok = ok; this.state = 'feedback'; this.tNext = now + 900; this.tRes = now; markDot(ok); success(ok);
    if (ok) {
      const rt = t.rt != null && t.rt >= 120 && t.rt <= 2000 ? t.rt : null;
      award((100 + (rt ? Math.max(0, (900 - rt) / 5) : 0)) * mult(S.streak), headPoint(), rt && rt < 400 ? T('perfect') : T('dodged'), '#22c55e');
      S.streak++; flash('ok'); sfx.cheer();
      if (rt) ART.floatText(headPoint().x, headPoint().y + 80 * DPR, `${rt} ms`, { color: '#22d3ee', size: 30 * DPR, life: 1.2 });
    } else { S.streak = 0; sfx.bad(); flash('bad'); award(0, headPoint(), T('tagged'), '#ef4444'); }
    setCombo(S.streak);
  }
  draw(g, V_, now) {
    if (!S.base || (this.state !== 'cue' && this.state !== 'feedback')) return;
    const footY = V(0, S.base.ankY).y, h = S.base.bodyPx * V.s * 0.95;
    const fromX = this.side === 'L' ? -0.2 * S.vw : 1.2 * S.vw, toX = S.base.hipX;
    const pAt = (tt) => (tt - this.t0) / this.win;
    let p = this.state === 'cue' ? pAt(now) : pAt(this.tRes);
    if (this.state === 'feedback') p += this.ok ? (now - this.tRes) / this.win * 1.3 : 0;
    const x = V(fromX + (toX - fromX) * Math.min(p, this.ok ? 3 : 1), 0).x, dir = this.side === 'L' ? 1 : -1;
    const fade = this.state === 'feedback' && this.ok ? clamp(1 - (now - this.tRes) / 800, 0, 1) : 1;
    const hop = this.state === 'feedback' && !this.ok ? Math.abs(Math.sin((now - this.tRes) / 90)) * 20 * DPR : 0;
    if (Math.random() < 0.3 && this.state === 'cue') ART.dust(x - dir * h * 0.15, footY, 1);
    ART.drawRunner(g, x, footY - hop, h, ART.PALETTE.raider, { dir, phase: now / 55, lean: 0.42, reach: 1, alpha: fade });
    if (this.state === 'cue' && S.mode !== 'blind') {
      const hp = V(S.base.hipX + (this.side === 'L' ? 1 : -1) * S.base.sw * 1.9, S.base.hipY - S.base.bodyPx * 0.15);
      drawArrow(g, hp.x + Math.sin(now / 80) * 8 * DPR, hp.y, this.side === 'L' ? 1 : -1, 110 * DPR);
    }
  }
}

class Jump extends Level {
  constructor(n, speed) { super('jump'); this.n = n; this.travel = 2200 / speed; this.i = 0; this.hist = []; this.logs = []; }
  start(now) { S.dots = []; setDots(this.n); this.next(now + 700); }
  next(at) {
    this.state = 'roll'; this.rawY = []; this.t0 = at; this.tArr = at + this.travel; this.peak = 0; this.tPeak = null; this.beeped = false; this.lastBeep = 0; this.live = 0;
    this.logs.push({ t0: at, tArr: this.tArr, hit: null });
    SIM && SIM.cue('jump', { tArr: this.tArr });
  }
  update(now) {
    const b = S.body;
    if (b) { this.hist.push({ t: now, y: b.hipY }); this.hist = this.hist.filter((h) => now - h.t < 4000); }
    if (this.state !== 'roll') return;
    if (S.mode === 'blind' && now - this.lastBeep > 260 && now < this.tArr) {   // approaching tone, rising pitch
      this.lastBeep = now; const p = clamp((now - this.t0) / this.travel, 0, 1); tone(400 + 700 * p, 70, { pan: 1 - p });
    }
    if (!this.beeped && now > this.tArr - 220) { this.beeped = true; sfx.go(); ART.floatText(headPoint().x, headPoint().y - 60 * DPR, T('jump_now'), { color: '#fde047', size: 70 * DPR, life: 0.6 }); }
    const winStart = this.tArr - 400, winEnd = this.tArr + 300;
    if (now >= winStart && now <= winEnd && b) {
      const ref = this.hist.filter((h) => h.t > this.t0 - 200 && h.t < winStart - 100).map((h) => h.y);
      const base = ref.length ? median(ref) : S.base.hipY;
      this.rawY = (this.rawY || []).concat(S.bodyRaw ? [S.bodyRaw.hipY] : []).slice(-3);
      const rise = base - (this.rawY.length ? median(this.rawY) : b.hipY);
      this.live = Math.max(0, rise * (S.calib.cm_per_px || 0.5));
      if (rise > this.peak) { this.peak = rise; this.tPeak = now; }
    }
    if (now > winEnd) {
      const cm = this.peak * (S.calib.cm_per_px || 0.5);
      const ok = cm >= 5 && this.tPeak != null;
      const t = { ok, rise_px: Math.round(this.peak), cm: +cm.toFixed(1), timing: this.tPeak ? Math.round(this.tPeak - this.tArr) : null };
      S.raw.jump.push(t); this.logs[this.logs.length - 1].hit = !ok;
      markDot(ok); success(ok);
      if (ok) {
        const grade = t.timing != null && Math.abs(t.timing) <= 100 ? T('perfect') : T('cleared');
        award(100 + 3 * Math.min(t.cm, 60) + (t.timing != null && Math.abs(t.timing) <= 100 ? 50 : t.timing != null && Math.abs(t.timing) <= 200 ? 20 : 0), headPoint(), grade, '#22c55e');
        ART.floatText(headPoint().x, headPoint().y + 84 * DPR, `${Math.round(cm)} cm`, { color: '#22d3ee', size: 34 * DPR, life: 1.3 });
        flash('ok'); ART.dust(V(S.base.hipX, 0).x, V(0, S.base.ankY).y, 12);
      } else { sfx.thud(); flash('bad'); award(0, headPoint(), T('hit'), '#ef4444'); }
      this.i++; this.live = 0;
      if (this.i >= this.n) { this.state = 'done'; setTimeout(() => this.finish(true), 900); } else this.next(now + 1400);
    }
  }
  draw(g, V_, now) {
    if (!S.base) return;
    const footY = V(0, S.base.ankY).y, r = S.base.bodyPx * 0.075 * V.s, startX = V(S.vw * 1.15, 0).x, hitX = V(S.base.hipX, 0).x;
    for (const L of this.logs) {
      let p = (now - L.t0) / (L.tArr - L.t0);
      if (p < 0) continue;
      let x = startX + (hitX - startX) * p, y = footY;
      if (L.hit && p > 1) { const k = (p - 1) * (L.tArr - L.t0) / 1000; x = hitX + 60 * DPR * k * 3; y = footY - Math.abs(Math.sin(k * 9)) * r * 2 * Math.exp(-k * 3); }
      if (x < -r * 4) continue;
      ART.drawLog(g, x - r, y, r, -(x - startX) / r);
    }
    // height meter while airborne
    if (this.state === 'roll' && now > this.tArr - 500) {
      const hp = V(S.base.hipX - S.base.sw * 2.2, S.base.hipY), H = 160 * DPR, w = 26 * DPR, fill = clamp(this.live / 45, 0, 1);
      g.save(); g.fillStyle = '#1e1b4bcc'; g.fillRect(hp.x - w / 2, hp.y - H / 2, w, H);
      g.fillStyle = fill > 0.5 ? '#22c55e' : '#fde047'; g.fillRect(hp.x - w / 2, hp.y + H / 2 - H * fill, w, H * fill);
      g.strokeStyle = '#fff'; g.lineWidth = 3; g.strokeRect(hp.x - w / 2, hp.y - H / 2, w, H); g.restore();
      bigText(g, `${Math.round(this.live)}cm`, hp.x, hp.y - H / 2 - 22 * DPR, 26 * DPR, '#fff');
    }
  }
}

class Escape extends Level {
  constructor(secs) { super('escape'); this.secs = secs; this.steps = 0; this.sign = 0; this.gap = 0; this.rate = 0; this.lastStep = 0; }
  start(now) {
    this.t0 = now; this.state = 'run'; this.gap = 3; sfx.go();
    SIM && SIM.cue('escape', { until: this.t0 + this.secs * 1000 });
  }
  update(now) {
    if (this.state !== 'run') return;
    const b = S.body, dt = Math.min(0.05, (now - (this.lastT || now)) / 1000); this.lastT = now;
    if (b) {   // a step = the knees swap which one is higher
      const d = b.lk.y - b.rk.y, thr = 0.05 * S.base.bodyPx;
      let stepped = false;
      if (d > thr && this.sign !== 1) { if (this.sign) { this.steps++; stepped = true; } this.sign = 1; }
      else if (d < -thr && this.sign !== -1) { if (this.sign) { this.steps++; stepped = true; } this.sign = -1; }
      if (stepped) {
        this.rate = this.rate * 0.7 + 0.3 * (1000 / Math.max(120, now - (this.lastStep || now - 500))); this.lastStep = now;
        sfx.step(); ART.dust(V(S.base.hipX, 0).x, V(0, S.base.ankY).y, 2);
        if (this.steps % 10 === 0) { award(0, headPoint(), `${this.steps}!`, '#fde047'); sfx.cheer(); }
      }
    }
    this.rate *= Math.pow(0.4, dt);
    const target = 1.4 + clamp(this.rate / 4.5, 0, 1) * 2.6;           // fast feet keep the bull further away
    this.gap += (target - this.gap) * Math.min(1, dt * 1.5);
    S.scroll += (200 + this.rate * 220) * DPR * dt;
    const left = this.secs - (now - this.t0) / 1000;
    textTrial(`⏱ ${Math.max(0, Math.ceil(left))} s   👟 ${this.steps}`);
    if (left <= 0) {
      S.raw.escape = { steps: this.steps, secs: this.secs }; this.state = 'done';
      const fast = this.steps / this.secs >= 2.5;
      award(5 * Math.min(this.steps, 4 * this.secs), headPoint(), fast ? T('escaped') : T('phew'), fast ? '#22c55e' : '#fde047');
      success(true); sfx.cheer(true); this.finish(true);
    }
  }
  draw(g, V_, now) {
    if (this.state !== 'run' || !S.base) return;
    const footY = V(0, S.base.ankY).y, h = S.base.bodyPx * V.s * 0.62, x = V(S.base.hipX - this.gap * S.base.sw, 0).x;
    if (Math.random() < 0.4) ART.dust(x - h * 0.4, footY, 1, 'rgba(160,140,120,0.7)');
    ART.drawBull(g, x - h * 0.3, footY, h, now / 70, 1);
    const left = Math.max(0, this.secs - (now - this.t0) / 1000);
    bigText(g, `${Math.ceil(left)}`, VIEW.W * 0.88, VIEW.H * 0.3, 110 * DPR, left <= 3 ? '#ef4444' : '#fff');
  }
}

class Pulse extends Level {
  constructor(secs, idx) { super('pulse'); this.secs = secs; this.idx = idx; this.meter = new PulseMeter(); this.live = null; this.nag = 0; this.samRect = null; }
  finish(v) { SIM && SIM.cue('close', { on: false }); super.finish(v); }   // also when the level is skipped
  start() {
    this.state = 'approach'; caption(T('pulse_intro')); textTrial(this.idx === 0 ? '❤️ 1/2' : '❤️ 2/2');
    SIM && SIM.cue('close', { on: true, bpm: this.idx === 0 ? 102 : 84 });
  }
  update(now) {
    const b = S.body, lm = S.lm;
    const close = b && b.face && b.eyeDist > 0.065 * S.vw;
    if (this.state === 'approach') {
      if (S.mode === 'blind' && b && b.face && now - (this.lastBeep || 0) > 600) {
        this.lastBeep = now; tone(300 + 900 * clamp(b.eyeDist / (0.065 * S.vw), 0, 1), 90);
      }
      if (close) {
        this.state = 'measure'; this.tStart = now; this.tLast = now; say(T('pulse_measuring'), { wait: false });
        // SAM 3.1: the face region, used for the skin patch (falls back to eye landmarks)
        samBoxes('face', 7000).then((boxes) => {
          if (!boxes || !S.lm) return;
          const f = boxes[0], le = S.lm[2], re = S.lm[5];
          const ed = Math.hypot((le.x - re.x) * S.vw, (le.y - re.y) * S.vh) / S.vw, edY = ed * S.vw / S.vh;
          const mx = (le.x + re.x) / 2, my = (le.y + re.y) / 2, fw = f.x2 - f.x1, fh = f.y2 - f.y1;
          const fx = f.x1 + 0.25 * fw, fy = f.y1 + 0.12 * fh;      // forehead inside the SAM face box
          this.samRect = { dx: (fx - mx) / ed, dy: (fy - my) / edY, w: (0.5 * fw) / ed, h: (0.16 * fh) / edY };
        });
      }
      return;
    }
    if (this.state !== 'measure') return;
    if (!close) { if (now - this.nag > 3000) { this.nag = now; caption(T('pulse_back')); } return; }
    const rgb = roiMean(skinRects(lm, this.samRect));
    if (rgb) this.meter.add(now, rgb);
    if (now - this.tLast > 1000) { this.tLast = now; const e = this.meter.estimate(); if (e && e.quality > 0.2) this.live = e.bpm; }
    if (this.meter.seconds >= this.secs) {
      const e = this.meter.estimate() || { bpm: null, quality: 0 };
      const rec = { bpm: e.bpm, quality: e.quality, secs: +this.meter.seconds.toFixed(1), method: this.samRect ? 'sam-3.1' : 'landmarks' };
      S.raw.pulse.push(rec);
      this.state = 'done'; sfx.levelUp();
      const ok = rec.bpm && rec.quality >= 0.25;
      award(ok ? 150 : 50, headPoint(), T('heart_ok'), '#f43f5e');
      if (rec.bpm) ART.floatText(headPoint().x, headPoint().y + 90 * DPR, `❤ ${rec.bpm} bpm`, { color: '#fff', size: 44 * DPR, life: 1.8, stroke: '#9f1239' });
      SIM && SIM.cue('close', { on: false });
      say(T(S.scope === 'upper' ? 'step_back_upper' : 'step_back')).then(() => this.finish(true));
    }
  }
  draw(g, V_, now) {
    let c = { x: VIEW.W / 2, y: VIEW.H * 0.42 }, r = VIEW.H * 0.24;
    if (S.lm && S.body && S.body.face) {
      const le = lmScreen(S.lm, 2), re = lmScreen(S.lm, 5), n = lmScreen(S.lm, 0);
      c = { x: (le.x + re.x + n.x) / 3, y: (le.y + re.y + n.y) / 3 }; r = Math.max(60 * DPR, Math.hypot(le.x - re.x, le.y - re.y) * 2.3);
    }
    if (this.state === 'approach') {
      g.save(); g.strokeStyle = '#fde047'; g.lineWidth = 6 * DPR; g.setLineDash([18 * DPR, 12 * DPR]); g.lineDashOffset = -now / 20;
      g.beginPath(); g.arc(VIEW.W / 2, VIEW.H * 0.42, VIEW.H * 0.26, 0, Math.PI * 2); g.stroke(); g.restore();
      bigText(g, '⬆ ' + (S.lang === 'en' ? 'COME CLOSER' : '❤'), VIEW.W / 2, VIEW.H * 0.82, 44 * DPR, '#fde047');
      return;
    }
    if (this.state !== 'measure') return;
    ART.drawScanner(g, c.x, c.y, r, now / 1000, clamp(this.meter.seconds / this.secs, 0, 1), this.live);
    const beat = this.live ? 1 + 0.18 * Math.max(0, Math.sin(now / 1000 * Math.PI * 2 * this.live / 60)) : 1;
    g.save(); g.font = `${Math.round(64 * beat * DPR)}px system-ui`; g.textAlign = 'center'; g.textBaseline = 'middle';
    g.fillText('❤️', c.x + r * 1.55, c.y - r * 0.6); g.restore();
    bigText(g, this.live ? `${this.live}` : '…', c.x + r * 1.55, c.y + r * 0.05, 60 * DPR, '#fff', '#9f1239');
    bigText(g, 'BPM', c.x + r * 1.55, c.y + r * 0.45, 26 * DPR, '#fda4af', '#9f1239');
  }
}

class Bowler extends Level {
  constructor(n, hardShare) {
    super('bowler'); this.n = n; this.i = 0;
    const hard = clamp(Math.round(n * hardShare), 1, n - 2), easy = Math.min(2, n - hard - 1), med = n - hard - easy;
    this.levels = [...Array(easy).fill('easy'), ...Array(med).fill('medium'), ...Array(hard).fill('hard')];
    const half = Math.floor(n / 2); this.targets = [...Array(half).fill('L'), ...Array(n - half).fill('R')].sort(() => Math.random() - 0.5);
  }
  start() { this.state = 'center'; this.tc = null; S.dots = []; setDots(this.n); }
  get playerAlpha() { return S.mode !== 'blind' && this.state === 'anim' ? 0.6 : 1; }   // see-through as a backup; the player stands aside anyway
  update(now) {
    const b = S.body;
    if (this.state === 'center') {
      if (centered(b)) { this.tc = this.tc || now; if (now - this.tc > 400) this.begin(now); } else this.tc = null;
    } else if (this.state === 'anim' || this.state === 'occluded') {
      const t = now - this.t0;
      if (this.state === 'anim' && t >= this.tOcc) {
        this.state = 'occluded'; S.darkTarget = 1; sfx.lightsOut(); caption(T('where'));
        if (S.mode !== 'blind') ART.floatText(VIEW.W / 2, VIEW.H * 0.3, '⚡ ' + T('lights'), { color: '#fde047', size: 58 * DPR, life: 1.0 });
      }
      if (b && t > 1100 && !this.answer) {
        const d = posX(b) - S.base.hipX;                  // step - or lean, in the upper-body game
        if (Math.abs(d) > (S.scope === 'upper' ? 0.4 : 0.45) * S.base.sw) { this.answer = d < 0 ? 'L' : 'R'; this.rt = Math.round(now - this.t0 - this.tOcc); }
      }
      if (S.mode === 'blind' && this.state === 'anim' && t > 1300 && now - (this.lastBeep || 0) > 120) {
        this.lastBeep = now; const pan = (this.target === 'L' ? -1 : 1) * clamp((t - 1300) / 900, 0, 1) * 0.9;
        tone(500 + (t - 1300) * 0.6, 90, { pan, type: 'triangle' });
      }
      if (this.answer || t > this.tOcc + 1700) this.resolve(now);
    } else if (this.state === 'reveal' && now > this.tNext) {
      this.i++; if (this.i >= this.n) return this.finish(true);
      this.state = 'center'; this.tc = null;
    }
  }
  begin(now) {
    this.level = this.levels[this.i]; this.target = this.targets[this.i]; this.answer = null; this.rt = null;
    this.t0 = now; this.state = 'anim'; S.darkTarget = 0;
    this.tOcc = 1750 + { easy: 180, medium: 0, hard: -150 }[this.level];
    if (S.mode === 'blind') this.tOcc = 1300 + { easy: 450, medium: 300, hard: 150 }[this.level];
    setDots(this.n, this.level.toUpperCase());
    SIM && SIM.cue('bowler', { t0: now, tOcc: now + this.tOcc, target: this.target, level: this.level });
  }
  resolve(now) {
    S.raw.bowler.push({ level: this.level, target: this.target, answer: this.answer, rt: this.rt });
    const ok = this.answer === this.target;
    S.darkTarget = 0; markDot(ok); success(ok);
    if (ok) { award(150 * BOWL_MULT[this.level] * mult(S.streak), headPoint(), T('correct'), '#22c55e'); S.streak++; sfx.hit(); sfx.cheer(); flash('ok'); }
    else { S.streak = 0; sfx.bad(); flash('bad'); award(0, headPoint(), T('wrong'), '#ef4444'); }
    setCombo(S.streak);
    this.state = 'reveal'; this.tNext = now + 1300; this.tRes = now; this.okLast = ok;
  }
  drawBack(g, V_, now) {
    if (S.mode === 'blind' || !S.base || !['anim', 'occluded', 'reveal'].includes(this.state)) return;
    if (this.state === 'occluded' || (this.state === 'anim' && now - this.t0 >= this.tOcc)) return;   // lights out: nothing to see
    const t = (now - this.t0) / 1000, dir = this.target === 'L' ? -1 : 1;
    const groundY = groundLine(), cx = BOWLER_AT * VIEW.W;           // in the open part of the screen, never behind the player
    this.bw = ART.drawBowler(g, cx, groundY, VIEW.H, this.state === 'reveal' ? 1.75 : Math.min(t, 1.75), dir, { showBall: this.state === 'reveal' });
  }
  draw(g, V_, now) {
    if (this.state !== 'reveal' || !this.bw || S.mode === 'blind') return;
    const dir = this.target === 'L' ? -1 : 1, u = clamp((now - this.tRes) / 450, 0, 1);
    const from = this.bw.hand, end = V(S.base.hipX + dir * S.base.sw * 2.6, S.base.hipY - S.base.bodyPx * 0.05);
    const to = { x: clamp(end.x, VIEW.W * 0.04, VIEW.W * 0.96), y: end.y };
    const bx = from.x + (to.x - from.x) * u, by = from.y + (to.y - from.y) * u - Math.sin(u * Math.PI) * 60 * DPR;
    g.save(); g.strokeStyle = 'rgba(255,255,255,0.5)'; g.lineWidth = 10 * DPR * u; g.lineCap = 'round';
    g.beginPath(); g.moveTo(from.x + (to.x - from.x) * Math.max(0, u - 0.3), from.y + (to.y - from.y) * Math.max(0, u - 0.3)); g.lineTo(bx, by); g.stroke(); g.restore();
    ART.drawBall(g, bx, by, (10 + 22 * u) * DPR, now / 40);
  }
}

// Shadow Boxing (upper-body game): punch the pads that pop up left and right. It raises the heart
// rate before the heart scan, like Bull Run does in the full-body game. Points only - no talent trait.
class Boxing extends Level {
  // A real punch goes towards the camera, so it is read in 3D (PunchDetector in motion.js); hooks out to the
  // side are read in 2D. A pad on the left of the screen is for the left fist (the view is a mirror), but a
  // cross from the other hand that lands on that side counts too. Each fist must come back before it scores again.
  constructor(secs) { super('boxing'); this.secs = secs; this.hits = 0; this.pads = 0; this.rts = []; this.pad = null; this.nextAt = 0; this.pd = new PunchDetector(); this.kinds = { forward: 0, side: 0 }; }
  start(now) {
    this.t0 = now; this.state = 'run'; sfx.go(); this.nextAt = now + 800;      // a moment to raise the guard
    SIM && SIM.cue('boxing', { until: now + this.secs * 1000 });
  }
  spawn(now) {
    const side = this.pads === 0 ? 1 : Math.random() < 0.5 ? -1 : 1;     // screen side
    this.pad = { side, t: now, dy: rand(-0.5, -0.1) }; this.pads++;
    if (S.mode === 'blind') tone(side < 0 ? 520 : 780, 90, { pan: side * 0.9 });
    SIM && SIM.cue('pad', { side, t: now });
  }
  padAt(b) {     // video pixels, mirrored like bodyInfo: in front of that shoulder, at face height
    const sw = S.base.sw, sx = b ? b.shX : S.base.hipX, sy = b ? b.shY : S.base.hipY - 1.5 * sw;
    return { x: sx + this.pad.side * 1.3 * sw, y: sy + this.pad.dy * sw };
  }
  update(now) {
    if (this.state !== 'run') return;
    const left = this.secs - (now - this.t0) / 1000;
    textTrial(`⏱ ${Math.max(0, Math.ceil(left))} s   🥊 ${this.hits}`);
    if (!this.pad && now >= this.nextAt) this.spawn(now);
    // raw points (no smoothing lag: a punch lasts ~0.2 s)
    const punches = this.pd.feed(now, S.lmRaw, S.worldRaw, { vw: S.vw, vh: S.vh });
    if (this.pad && S.body) {
      const p = this.padAt(S.body);
      const hit = punches.find((pu) => (pu.arm === 'L' ? -1 : 1) === this.pad.side || pu.sideOf === this.pad.side);
      if (hit && now - this.pad.t > 100) {           // faster than 0.1 s after the pad appeared = already punching, not a reaction
        this.hits++; this.rts.push(now - this.pad.t); this.kinds[hit.kind]++;
        const at = V(p.x, p.y);
        sfx.hit(); ART.burst(at.x, at.y, { n: 18, size: 8 * DPR, speed: 380 * DPR, gravity: 600 * DPR });
        award(50, at, this.hits % 5 === 0 ? `${this.hits}!` : T('pow'), '#fde047');
        if (this.hits % 10 === 0) sfx.cheer();
        this.pad = null; this.nextAt = now + 150;
      } else if (now - this.pad.t > 1800) { this.pad = null; this.nextAt = now + 100; }
    }
    if (left <= 0) {
      this.state = 'done';
      S.raw.boxing = { hits: this.hits, pads: this.pads, secs: this.secs, median_ms: this.rts.length ? Math.round(median(this.rts)) : null, forward: this.kinds.forward, side: this.kinds.side };
      success(true); sfx.cheer(true); this.finish(true);
    }
  }
  draw(g, V_, now) {
    if (this.state !== 'run' || !S.base) return;
    if (this.pad) {
      const p = V(...Object.values(this.padAt(S.body))), r = 0.75 * S.base.sw * V.s, age = (now - this.pad.t) / 1800;
      g.save();
      g.fillStyle = this.pad.side < 0 ? '#ef4444' : '#3b82f6'; g.strokeStyle = '#fff'; g.lineWidth = 6 * DPR;
      g.shadowColor = g.fillStyle; g.shadowBlur = 24;
      g.beginPath(); g.arc(p.x, p.y, r * (0.9 + 0.08 * Math.sin(now / 90)), 0, Math.PI * 2); g.fill(); g.stroke();
      g.shadowBlur = 0; g.strokeStyle = '#fde047'; g.lineWidth = 8 * DPR;      // time ring
      g.beginPath(); g.arc(p.x, p.y, r * 1.15, -Math.PI / 2, -Math.PI / 2 + (1 - age) * Math.PI * 2); g.stroke();
      g.font = `${Math.round(r)}px system-ui`; g.textAlign = 'center'; g.textBaseline = 'middle'; g.fillText('🥊', p.x, p.y + 2 * DPR);
      g.restore();
    }
    // guard reminder: both fists up by the chin
    if (now - this.t0 < 2500 && S.mode !== 'blind') bigText(g, '✊ ✊', VIEW.W / 2, VIEW.H * 0.22, 60 * DPR, '#fde047');
    const left = Math.max(0, this.secs - (now - this.t0) / 1000);
    bigText(g, `${Math.ceil(left)}`, VIEW.W * 0.88, VIEW.H * 0.3, 110 * DPR, left <= 3 ? '#ef4444' : '#fff');
  }
}

const COMBO_MOVES = ['hands_up', 'left_hand_up', 'right_hand_up', 'arms_out', 'hands_on_head', 'hands_on_hips', 'squat'];
class Combo extends Level {
  constructor(len, tries) {
    super('combo'); this.tries = tries; this.k = 0; this.pattern = [];
    const moves = S.scope === 'upper' ? COMBO_MOVES.filter((m) => m !== 'squat' && m !== 'hands_on_hips') : COMBO_MOVES;
    while (this.pattern.length < len) {
      const m = moves[Math.floor(Math.random() * moves.length)];
      if (m !== this.pattern[this.pattern.length - 1]) this.pattern.push(m);
    }
    S.raw.combo = { pattern: this.pattern, tries: [] };
  }
  start() { this.show(); }
  async show() {
    this.state = 'show'; textTrial(`🎵 ${this.k + 1} / ${this.tries}`); this.tShow = performance.now();
    this.stepMs = FAST ? 600 / this.pattern.length : 1100;
    const list = this.pattern.map((m, i) => `${i + 1}. ${moveText(m)}`).join('. ');
    await Promise.all([say(list), sleep(FAST ? 600 : this.stepMs * this.pattern.length + 500)]);
    this.state = 'perform'; this.got = []; this.tracker = new MoveTracker(); this.hintT = 0;
    this.tStart = performance.now();
    // the standing hip height right now (player resting while the coach danced): a squat = the hips dropping from here
    const st = this.stand || [];
    this.base = S.scope === 'full' && st.length >= 5 ? { hipY: median(st.map((x) => x.hip)), torso: median(st.map((x) => x.torso)) }
              : S.scope === 'full' && S.base ? { hipY: S.base.hipY, torso: 0.32 * S.base.bodyPx } : null;
    say(T('combo_go'), { wait: false }); sfx.go();
    SIM && SIM.cue('combo', { pattern: this.pattern, tryIndex: this.k, t0: this.tStart });
  }
  update(now) {
    if (this.state === 'show') {         // remember how the player stands at rest, for the squat
      const b = S.body;
      if (b && b.full && S.lm) { (this.stand = this.stand || []).push({ t: now, hip: b.hipY, torso: b.hipY - b.shY }); this.stand = this.stand.filter((x) => now - x.t < 1500); }
      return;
    }
    if (this.state !== 'perform') return;
    const mv = S.lm ? classifyMove(S.lm, { vw: S.vw, vh: S.vh, scope: S.scope, base: this.base }) : 'unknown';
    const stable = this.tracker.feed(now, mv, S.lm);
    // close to the camera with the head at the very top: raised hands leave the picture
    if (S.scope === 'upper' && S.body && S.body.nose.y < 0.1 * S.vh && now - this.hintT > 6000) { this.hintT = now; caption(T('hands_in_view')); }
    if (stable) {
      this.got.push(stable);
      const ok = this.pattern[this.got.length - 1] === stable;
      if (ok) { sfx.ok(); ART.floatText(headPoint().x, headPoint().y - 30 * DPR, '✓', { color: '#22c55e', size: 70 * DPR, life: 0.7 }); }
      else { sfx.bad(); ART.floatText(headPoint().x, headPoint().y - 30 * DPR, '✗', { color: '#ef4444', size: 70 * DPR, life: 0.7 }); }
      flash(ok ? 'ok' : 'bad'); caption(`${this.got.length}. ${moveText(stable)}`);
    }
    const rest = this.tracker.restingFor;
    const timeout = this.pattern.length * 3000 + 4000;
    if ((this.got.length >= this.pattern.length && rest && now - rest > 150) ||
        (this.got.length && rest && now - rest > 2500) || now - this.tStart > timeout) this.endTry();
  }
  async endTry() {
    this.state = 'review';
    S.raw.combo.tries.push({ done: [...this.got] });
    const { dist, firstBad } = editDistance(this.pattern, this.got);
    const pts = 50 * Math.max(0, this.pattern.length - dist) + (dist === 0 ? 300 : 0);
    award(pts, headPoint(), dist === 0 ? T('perfect') : dist <= 1 ? T('good') : '', dist === 0 ? '#22c55e' : '#fde047');
    if (dist === 0) { ART.burst(VIEW.W / 2, VIEW.H * 0.3, { n: 60, size: 10 * DPR, speed: 600 * DPR, gravity: 700 * DPR }); sfx.cheer(true); S.excite = 1; }
    const tip = dist === 0 ? T('perfect') : I18N[S.lang].try_tip(this.k + 1, dist, firstBad + 1, moveText(this.pattern[firstBad]));
    await say(tip);
    this.k++;
    if (this.k >= this.tries) this.finish(true); else this.show();
  }
  drawBack(g, V_, now) {
    // the dancing coach on the stage: shows each move in time with the music, then waits
    const groundY = S.base ? groundLine() : VIEW.H * 0.92, boxH = VIEW.H * 0.5, cx = Math.max(VIEW.W * 0.14, V(S.vw * 0.12, 0).x);
    let move = 'hands_on_hips';
    if (this.state === 'show') { const i = Math.floor((now - this.tShow) / this.stepMs); move = this.pattern[clamp(i, 0, this.pattern.length - 1)]; }
    const bounce = beatPulse() * 6 * DPR, P = ART.movePose(move), Q2 = {};
    for (const k in P) Q2[k] = { x: cx + ((1 - P[k][0]) - 0.5) * boxH, y: groundY - (0.9 - P[k][1]) * boxH - bounce };
    ART.drawFigure(g, Q2, ART.PALETTE.coach, { glowColor: this.state === 'show' ? '#f472b6' : null });
    if (this.state === 'show') bigText(g, MOVE_TEXT[move].icon, cx, groundY - boxH - 30 * DPR, 54 * DPR);
  }
  draw(g, V_, now) {
    if (this.state !== 'show' && this.state !== 'perform' && this.state !== 'review') return;
    // live feedback: what the camera reads right now, and a ring that fills while the move is held
    if (this.state === 'perform' && this.tracker && S.mode !== 'blind') {
      const rd = this.tracker.reading, hp = { x: Math.max(VIEW.W * 0.13, 150 * DPR) }, y = 150 * DPR;   // fixed spot, top-left: never on the face
      if (rd !== 'unknown' && rd !== 'neutral' && MOVE_TEXT[rd]) {
        const pr = this.tracker.progress;
        g.save(); g.lineWidth = 9 * DPR; g.strokeStyle = '#ffffff33'; g.beginPath(); g.arc(hp.x, y, 40 * DPR, 0, Math.PI * 2); g.stroke();
        g.strokeStyle = '#22d3ee';   // same colour for every move: it shows what is read, not whether it is right g.beginPath(); g.arc(hp.x, y, 40 * DPR, -Math.PI / 2, -Math.PI / 2 + pr * Math.PI * 2); g.stroke(); g.restore();
        g.save(); g.font = `${Math.round(40 * DPR)}px system-ui`; g.textAlign = 'center'; g.textBaseline = 'middle'; g.fillText(MOVE_TEXT[rd].icon, hp.x, y + 2 * DPR); g.restore();
        bigText(g, `${T('sees')}: ${moveText(rd)}`, hp.x, y + 66 * DPR, 22 * DPR, '#fff');
      }
    }
    // the move cards stand in a column on the right, so they never cover the player
    const n = this.pattern.length, ch = Math.min(130 * DPR, (VIEW.H * 0.72) / n), w = Math.min(150 * DPR, ch * 1.15), h = ch - 10 * DPR;
    const x = VIEW.W - w - 22 * DPR, y0 = Math.max(100 * DPR, (VIEW.H - ch * n) / 2);
    const cur = this.state === 'show' ? Math.floor((now - this.tShow) / this.stepMs) : this.state === 'perform' ? (this.got || []).length : -1;
    for (let i = 0; i < n; i++) {
      const y = y0 + i * ch;
      const got = (this.state !== 'show') && i < (this.got || []).length;
      const okI = got && this.got[i] === this.pattern[i];
      g.save();
      g.fillStyle = got ? (okI ? '#16a34a' : '#dc2626') : i === cur ? '#db2777' : '#1e1b4b';
      g.strokeStyle = i === cur ? '#fde047' : '#ffffff66'; g.lineWidth = 4 * DPR;
      g.shadowColor = i === cur ? '#f472b6' : 'transparent'; g.shadowBlur = 20;
      g.beginPath(); g.roundRect ? g.roundRect(x, y, w, h, 16 * DPR) : g.rect(x, y, w, h); g.fill(); g.stroke(); g.restore();
      bigText(g, `${i + 1}`, x + 20 * DPR, y + 22 * DPR, 22 * DPR, '#fde047');
      g.save(); g.font = `${Math.round(Math.min(48 * DPR, h * 0.5))}px system-ui`; g.textAlign = 'center'; g.textBaseline = 'middle';
      const icon = this.state === 'show' ? (i <= cur ? MOVE_TEXT[this.pattern[i]].icon : '•') : got ? (MOVE_TEXT[this.got[i]]?.icon || '?') : '?';   // memory test: next moves stay hidden
      g.fillStyle = '#fff'; g.fillText(icon, x + w / 2 + 8 * DPR, y + h / 2 + 4 * DPR); g.restore();
    }
  }
}

// ------------------------------------------------------------------ local talent scoring (same formulas as arena_score.py;
// the server's numbers replace these as soon as it answers)
const LABELS = { reflex: 'Reflexes', agility: 'Agility', power: 'Power', anticipation: 'Game reading', learning: 'Learning speed', heart: 'Heart recovery' };
function localProfile(raw) {
  const c01 = (x) => clamp(x, 0, 1); const tr = {};
  const d = raw.dodge || [];
  if (d.length >= 3) {
    const ok = d.filter((t) => t.ok), rts = ok.map((t) => t.rt).filter((r) => r != null && r >= 120 && r <= 2000);
    const pk = ok.map((t) => t.peak_v).filter((p) => p != null && p <= 15);
    tr.reflex = rts.length ? +(100 * c01((900 - median(rts)) / 650)).toFixed(1) : null;
    tr.agility = +(100 * (0.5 * ok.length / d.length + 0.5 * c01((pk.length ? median(pk) : 0) / 4))).toFixed(1);
  }
  if ((raw.jump || []).length) { const hs = raw.jump.filter((j) => j.ok).map((j) => j.cm); tr.power = +(100 * c01((hs.length ? Math.max(...hs) : 0) / 45)).toFixed(1); }
  const bw = (raw.bowler || []).filter((t) => t.answer);
  if (bw.length >= 4) { const w = bw.reduce((a, t) => a + LEVEL_WEIGHT[t.level], 0), h = bw.filter((t) => t.answer === t.target).reduce((a, t) => a + LEVEL_WEIGHT[t.level], 0); tr.anticipation = +(100 * c01((h / w - 0.5) / 0.5)).toFixed(1); }
  if (raw.combo && raw.combo.tries.length) {
    const e = raw.combo.tries.map((t) => editDistance(raw.combo.pattern, t.done).dist), n = raw.combo.pattern.length;
    const last2 = e.slice(-2), fin = last2.reduce((a, b) => a + b, 0) / last2.length, acc = c01(1 - fin / n);
    tr.learning = e[0] <= 0.5 ? +(75 + 15 * acc).toFixed(1) : +(100 * (0.65 * c01((e[0] - fin) / e[0]) + 0.35 * acc)).toFixed(1);
  }
  const p = raw.pulse || [];
  if (p.length >= 2 && p[0].bpm && p[p.length - 1].bpm && p[0].quality >= 0.25 && p[p.length - 1].quality >= 0.25) tr.heart = +(100 * c01((p[0].bpm - p[p.length - 1].bpm) / 25)).toFixed(1);
  const vals = Object.values(tr).filter((v) => v != null);
  return { traits: Object.fromEntries(Object.keys(LABELS).map((k) => [k, tr[k] ?? null])), overall: vals.length ? +(vals.reduce((a, b) => a + b, 0) / vals.length).toFixed(1) : null, sports: [], labels: LABELS, details: {} };
}

// ------------------------------------------------------------------ results
function radarSvg(traits) {
  const keys = Object.keys(LABELS), cx = 160, cy = 150, R = 105;
  const pt = (i, r) => { const a = -Math.PI / 2 + i * 2 * Math.PI / keys.length; return [cx + Math.cos(a) * r, cy + Math.sin(a) * r]; };
  let s = '';
  for (const f of [0.25, 0.5, 0.75, 1]) s += `<polygon points="${keys.map((_, i) => pt(i, R * f).join(',')).join(' ')}" fill="none" stroke="#3b2a7a"/>`;
  keys.forEach((k, i) => { const [x, y] = pt(i, R); s += `<line x1="${cx}" y1="${cy}" x2="${x}" y2="${y}" stroke="#3b2a7a"/>`;
    const [lx, ly] = pt(i, R + 26); s += `<text x="${lx}" y="${ly}" fill="#e9e5ff" font-size="12" font-weight="800" text-anchor="middle" dominant-baseline="middle">${LABELS[k]}</text>`; });
  s += `<polygon points="${keys.map((k, i) => pt(i, R * (traits[k] ?? 0) / 100).join(',')).join(' ')}" fill="#22d3ee55" stroke="#22d3ee" stroke-width="3"/>`;
  return s;
}
function showProfile(p) {
  S.profile = p;
  $('radar').innerHTML = radarSvg(p.traits);
  const sc = p.scope || S.scope || 'full';
  $('scope-badge').textContent = (sc === 'upper' ? '🙋 ' : '🧍 ') + T(sc === 'upper' ? 'scope_upper' : 'scope_full');
  $('scope-badge').className = 'scope-badge ' + sc;
  $('scope-note').textContent = sc === 'upper' ? (p.scope_note || 'Reflexes, agility and power need the whole body in view - not measured, not zero.') : '';
  $('overall').innerHTML = p.overall == null ? 'Play more levels to get a score' : `Talent score <b>${Math.round(p.overall)}</b>`;
  $('trait-list').innerHTML = Object.keys(LABELS).map((k) => {
    const v = p.traits[k];
    return `<li class="${v == null ? 'nm' : ''}"><span>${LABELS[k]}</span><span class="bar"><i style="width:${v ?? 0}%"></i></span><b>${v == null ? (S.scope === 'upper' && ['reflex', 'agility', 'power'].includes(k) ? T('not_measured') : '–') : Math.round(v)}</b></li>`;
  }).join('');
  $('sports').innerHTML = (p.sports || []).map((s) => `<li>${s.sport} <span class="muted">· ${s.match}% match</span></li>`).join('') || '<li class="muted">Finish more levels to see matches.</li>';
  const pc = (p.details && p.details.pulse && p.details.pulse.checks) || S.raw.pulse.map((x) => ({ bpm: x.bpm, ok: x.quality >= 0.25 }));
  $('pulse-line').textContent = pc.length ? `Pulse (camera estimate): ${pc.map((c) => (c.bpm ? c.bpm + ' bpm' + (c.ok ? '' : ' (low confidence)') : 'not measured')).join(' → ')}` : '';
}
function showPoints(pt) {
  S.serverPoints = pt;
  $('rank-icon').textContent = pt.rank_icon; $('rank-name').textContent = pt.rank.toUpperCase() + '!';
  $('total-stars').textContent = `${pt.stars}/${pt.max_stars}`;
  const el = $('total-pts'), target = pt.total, t0 = performance.now(), from = +el.dataset.v || 0;
  el.dataset.v = target;
  const tick = () => { const u = clamp((performance.now() - t0) / 1200, 0, 1); el.textContent = Math.round(from + (target - from) * (1 - Math.pow(1 - u, 3))).toLocaleString('en-IN'); if (u < 1) requestAnimationFrame(tick); };
  tick();
  try {
    const key = 'arena_best_' + (S.quick ? 'quick' : 'full'), best = +(localStorage.getItem(key) || 0);
    if (target > best && !S.sim) { localStorage.setItem(key, String(target)); $('best').hidden = best === 0; }
  } catch (e) { /* storage blocked */ }
}
async function postJSON(url, body, timeoutMs = 60000) {
  const ctl = new AbortController(); const to = setTimeout(() => ctl.abort(), timeoutMs);
  try { const r = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal: ctl.signal }); return await r.json(); }
  finally { clearTimeout(to); }
}
function boardHtml(rows, me) {
  if (!rows || !rows.length) return '<li class="muted">Be the first champion today!</li>';
  return rows.map((r) => `<li class="${me && r.name === me.name && r.points === me.points ? 'me' : ''}"><b>${r.points.toLocaleString('en-IN')}</b> ${esc(r.name)} ${r.rank_icon || ''}${r.simulated ? ' 🤖' : ''}</li>`).join('');
}
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
let BOARD_SCOPE = 'full';
async function loadBoard(me, scope) {
  if (scope) BOARD_SCOPE = scope;
  document.querySelectorAll('.board-scope').forEach((b) => b.classList.toggle('on', b.dataset.scope === BOARD_SCOPE));
  try {
    const d = await (await fetch(`/api/arena/leaderboard?scope=${BOARD_SCOPE}` + (S.sim ? '&sim=1' : ''))).json();
    $('board-today').innerHTML = boardHtml(d.today.slice(0, 5), me);
    $('board-today-full').innerHTML = boardHtml(d.today, me);
    $('board-all').innerHTML = boardHtml(d.all_time, me);
  } catch (e) { $('board-today').innerHTML = '<li class="muted">Leaderboard offline</li>'; }
}
async function finishGame() {
  S.running = false; S.level = null; stopMusic(); $('hud').hidden = true; caption('');
  document.body.classList.add('show-results');
  S.world = 'stage'; sfx.victory(); ART.confetti(VIEW.W, VIEW.H, 180);
  $('results').hidden = false;
  const raw = rawPayload();
  showProfile(localProfile(raw)); showPoints(pointsFor(raw));
  try { const r = await postJSON('/api/arena/score', { raw }); if (r.ok) { showProfile(r.profile); if (r.points) showPoints(r.points); } } catch (e) { /* offline: local numbers stay */ }
  loadBoard(null, S.scope || 'full');
  say(T('results'), { wait: false });
  try {
    const r = await postJSON('/api/arena/coach', { raw, lang: S.lang, name: $('pname').value, age: $('page').value, plan_used: S.plan }, 70000);
    if (r.ok) {
      S.coach = r.coach; showProfile(r.profile);
      $('coach-src').textContent = r.coach.source === 'muse-spark' ? (r.coach.model || 'Muse Spark') : 'offline coach';
      $('coach-story').textContent = r.coach.story; $('coach-focus').textContent = '🎯 ' + r.coach.focus;
      $('coach-parents').textContent = '👪 ' + r.coach.tip_for_parents;
      const ns = r.coach.next_session;
      $('coach-next').textContent = `Next game: raiders ${ns.raider_window_ms} ms, logs ×${ns.log_speed}, hard bowler clips ${Math.round(ns.bowler_hard_share * 100)}%, dance combo of ${ns.combo_length}. ${ns.reason || ''}`;
      try { localStorage.setItem('arena_next_plan', JSON.stringify(ns)); } catch (e) { /* ignore */ }
      if (r.coach.source === 'muse-spark') S.ai.spark = 'yes';
      say(r.coach.story, { wait: false });
    }
  } catch (e) { $('coach-story').textContent = 'The coach is offline - your scores are above.'; }
}
function rawPayload() {
  return { calib: { method: S.calib.method, cm_per_px: S.calib.cm_per_px && +S.calib.cm_per_px.toFixed(4), body_px: S.calib.body_px },
           dodge: S.raw.dodge, jump: S.raw.jump, escape: S.raw.escape, pulse: S.raw.pulse, bowler: S.raw.bowler, combo: S.raw.combo,
           boxing: S.raw.boxing, scope: S.scope,
           plan_used: S.plan, quick: S.quick, mode: S.mode };
}
$('save-btn').addEventListener('click', async () => {
  $('save-btn').disabled = true; $('save-btn').textContent = 'Saving…';
  try {
    const r = await postJSON('/api/arena/save', { raw: rawPayload(), lang: S.lang, name: $('pname').value, age: $('page').value,
                                                  mode: S.mode, coach: S.coach, plan_used: S.plan, simulated: S.sim });
    if (!r.ok) throw new Error(r.error || 'save failed');
    S.saved = r; $('share').hidden = false;
    $('share-link').href = r.url; $('share-link').textContent = r.share_url;
    const box = $('qr'); box.innerHTML = '';
    const qrText = r.share_url + '?scan=1';
    try { new QRCode(box, { text: qrText, width: 140, height: 140 }); }
    catch (e) {
      const img = new Image(140, 140); img.alt = 'QR code for your verified card'; img.src = '/qr.svg?data=' + encodeURIComponent(qrText);
      img.onerror = () => { box.textContent = r.share_url; };
      box.appendChild(img);
    }
    $('save-btn').textContent = '✓ Saved - verified card ready';
    if (r.board && r.board.today) {
      $('board-pos').hidden = false;
      $('board-pos').innerHTML = `🏆 <b>#${r.board.today}</b> today of ${r.board.today_players}` + (r.board.scope === 'upper' ? ' (upper body)' : '');
      if (r.board.today === 1) { ART.confetti(VIEW.W, VIEW.H, 120); sfx.cheer(true); }
    }
    loadBoard({ name: r.display, points: r.points && r.points.total }, (r.points && r.points.scope) || S.scope);
  } catch (e) { $('save-btn').disabled = false; $('save-btn').textContent = '🪪 Save & get my verified card'; caption('Could not save: ' + e.message); }
});
$('poster-btn').addEventListener('click', async () => {
  $('poster-btn').disabled = true; $('poster-btn').textContent = '🎨 Muse Image is painting…';
  try {
    const r = await postJSON('/api/arena/art', { raw: rawPayload(), lang: S.lang }, 100000);
    if (!r.ok) throw new Error(r.error);
    $('poster').src = r.image; $('poster-box').hidden = false; $('poster-btn').textContent = '🎨 Poster ready'; S.ai.image = 'yes';
  } catch (e) { $('poster-btn').disabled = false; $('poster-btn').textContent = '🎨 Poster needs the Meta API key'; }
});
$('again-btn').addEventListener('click', () => { location.href = location.pathname + location.search.replace(/[?&]autostart=1/, ''); });

// ------------------------------------------------------------------ voice commands (Muse Voice Transcribe)
let rec = null;
async function startRec() {
  if (rec) return;
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const ac = new (window.AudioContext || window.webkitAudioContext)();
    const srcN = ac.createMediaStreamSource(stream), proc = ac.createScriptProcessor(4096, 1, 1), chunks = [];
    proc.onaudioprocess = (e) => chunks.push(new Float32Array(e.inputBuffer.getChannelData(0)));
    srcN.connect(proc); proc.connect(ac.destination);
    rec = { stream, ac, proc, srcN, chunks, t0: performance.now() };
    $('mic-btn').classList.add('rec');
  } catch (e) { caption('Microphone not available'); }
}
function wav16k(chunks, rate) {
  const n = chunks.reduce((a, c) => a + c.length, 0), all = new Float32Array(n); let o = 0;
  for (const c of chunks) { all.set(c, o); o += c.length; }
  const out = Math.floor(n * 16000 / rate), pcm = new Int16Array(out);
  for (let i = 0; i < out; i++) { const v = all[Math.min(n - 1, Math.floor(i * rate / 16000))]; pcm[i] = clamp(v, -1, 1) * 32767; }
  const buf = new ArrayBuffer(44 + pcm.length * 2), dv = new DataView(buf);
  const str = (off, s) => { for (let i = 0; i < s.length; i++) dv.setUint8(off + i, s.charCodeAt(i)); };
  str(0, 'RIFF'); dv.setUint32(4, 36 + pcm.length * 2, true); str(8, 'WAVE'); str(12, 'fmt '); dv.setUint32(16, 16, true);
  dv.setUint16(20, 1, true); dv.setUint16(22, 1, true); dv.setUint32(24, 16000, true); dv.setUint32(28, 32000, true);
  dv.setUint16(32, 2, true); dv.setUint16(34, 16, true); str(36, 'data'); dv.setUint32(40, pcm.length * 2, true);
  new Int16Array(buf, 44).set(pcm);
  return new Blob([buf], { type: 'audio/wav' });
}
async function stopRec() {
  if (!rec) return;
  const r = rec; rec = null; $('mic-btn').classList.remove('rec');
  r.proc.disconnect(); r.srcN.disconnect(); r.stream.getTracks().forEach((t) => t.stop());
  const blob = wav16k(r.chunks, r.ac.sampleRate); r.ac.close();
  if (performance.now() - r.t0 < 300) return;
  caption('🎤 …');
  try {
    const res = await fetch(`/api/arena/voice?lang=${S.lang}`, { method: 'POST', headers: { 'Content-Type': 'audio/wav' }, body: blob });
    const d = await res.json();
    if (!d.ok) { caption('Voice commands need the Meta API key'); S.ai.voice = 'no'; return; }
    S.ai.voice = 'yes'; caption(`🎤 "${d.transcript}"`); voiceIntent(d.intent);
  } catch (e) { caption('Voice command failed'); }
}
function voiceIntent(intent) {
  if (BONUS.open) { if (intent === 'start' || intent === 'next' || intent === 'yes') BONUS.answer(true); else if (intent === 'results' || intent === 'no') BONUS.answer(false); return; }
  if (intent === 'yes') intent = 'start';
  if (intent === 'start' && !S.started) startGame();
  else if (intent === 'next' && S.level && S.level.key !== 'calib') S.level.finish(false);
  else if (intent === 'repeat') say(S.lastSay || T('calib'));
  else if (intent === 'results' && !$('results').hidden) say(S.coach ? S.coach.story : T('results'));
  else if (intent === 'help') say(S.level && S.level.key !== 'calib' ? T(S.level.key + '_intro') : T('calib'));
}
$('mic-btn').addEventListener('pointerdown', startRec);
$('mic-btn').addEventListener('pointerup', stopRec);
$('mic-btn').addEventListener('pointerleave', () => rec && stopRec());
$('mute-btn').addEventListener('click', () => {
  setMuted(!SOUND.muted); $('mute-btn').textContent = SOUND.muted ? '🔇' : '🔊';
  if (SOUND.muted) try { speechSynthesis.cancel(); } catch (e) { /* ignore */ }
});
$('quit-btn').addEventListener('click', () => { if (S.running) { S.quit = true; if (S.level) S.level.finish(false); } });
document.addEventListener('keydown', (e) => {
  if (e.repeat || e.target.tagName === 'INPUT') return;
  if (BONUS.open && (e.code === 'Space' || e.key === 'y' || e.key === 'Y')) { e.preventDefault(); BONUS.answer(true); return; }
  if (BONUS.open && (e.key === 'Escape' || e.key === 'r' || e.key === 'R' || e.key === 'n' || e.key === 'N')) { BONUS.answer(false); return; }
  if (e.code === 'Space' && !S.started) { e.preventDefault(); startGame(); }
  if (e.key === 'v' || e.key === 'V') startRec();
  if (e.key === 'm' || e.key === 'M') $('mute-btn').click();
});
document.addEventListener('keyup', (e) => { if (e.key === 'v' || e.key === 'V') stopRec(); });

// ------------------------------------------------------------------ pose sources + the player's cut-out
let landmarker = null, SIM = null;
const PERSON = document.createElement('canvas'), PCTX = PERSON.getContext('2d');
const MASK = document.createElement('canvas'), MCTX = MASK.getContext('2d');
let maskImg = null;
async function startCamera() {
  const v = $('cam');
  const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'user', width: { ideal: 960 }, height: { ideal: 720 } }, audio: false });
  v.srcObject = stream; await v.play();
  S.src = v; S.vw = v.videoWidth || 640; S.vh = v.videoHeight || 480;
}
async function loadPose() {
  const mod = await import(`${MP_BASE}/vision_bundle.mjs`);
  const files = await mod.FilesetResolver.forVisionTasks(`${MP_BASE}/wasm`);
  POSE_MOD = mod; POSE_FILES = files;
  const opts = (delegate) => ({ baseOptions: { modelAssetPath: MP_MODEL_URL(MP_MODEL_NAME), delegate }, runningMode: 'VIDEO', numPoses: 1,
                                outputSegmentationMasks: S.view === 'camera',
                                minPoseDetectionConfidence: 0.5, minPosePresenceConfidence: 0.5, minTrackingConfidence: 0.5 });
  try { landmarker = await mod.PoseLandmarker.createFromOptions(files, opts('GPU')); }
  catch (e) {
    try { landmarker = await mod.PoseLandmarker.createFromOptions(files, opts('CPU')); }
    catch (e2) { if (MP_MODEL_NAME === 'lite') throw e2; MP_MODEL_NAME = 'lite'; return loadPose(); }   // model file not reachable: lite
  }
  POSE_OPTS = opts;
}
let POSE_MOD = null, POSE_FILES = null, POSE_OPTS = null, poseMs = [], poseSwitching = false;
// too slow for the "full" model on this device -> switch to "lite" once, without stopping the game
function checkPoseSpeed(ms) {
  if (MP_MODEL_NAME === 'lite' || poseSwitching || Q.get('model')) return;
  poseMs.push(ms); if (poseMs.length < 90) return;
  const mean = poseMs.reduce((a, b) => a + b, 0) / poseMs.length; poseMs = [];
  if (mean <= 55) return;
  poseSwitching = true; MP_MODEL_NAME = 'lite';
  const opts = POSE_OPTS;
  POSE_MOD.PoseLandmarker.createFromOptions(POSE_FILES, opts('GPU')).catch(() => POSE_MOD.PoseLandmarker.createFromOptions(POSE_FILES, opts('CPU')))
    .then((lm) => { const old = landmarker; landmarker = lm; lastTs = 0; try { old && old.close(); } catch (e) { /* ignore */ } })
    .catch(() => { MP_MODEL_NAME = 'full'; });
}
let maskPrev = null, maskCount = [], lightT = 0;
const LUMA = document.createElement('canvas'), LCTX = LUMA.getContext('2d', { willReadFrequently: true });
function updateMask(m) {
  const w = m.width, h = m.height, arr = m.getAsFloat32Array();
  if (MASK.width !== w || MASK.height !== h || !maskImg) { MASK.width = w; MASK.height = h; maskImg = MCTX.createImageData(w, h); maskPrev = null; }
  if (!maskPrev || maskPrev.length !== arr.length) maskPrev = new Float32Array(arr);
  const d = maskImg.data; let count = 0;
  for (let i = 0, j = 3; i < arr.length; i++, j += 4) {
    const v = 0.6 * arr[i] + 0.4 * maskPrev[i];              // steadier edges: less flicker frame to frame
    maskPrev[i] = v;
    const a = v <= 0.35 ? 0 : v >= 0.65 ? 1 : (v - 0.35) / 0.3;   // faint "ghost" areas cut away, edge kept soft
    d[j] = a * a * (3 - 2 * a) * 255;
    if (v > 0.5) count++;
  }
  MCTX.putImageData(maskImg, 0, 0);
  maskCount.push(count); if (maskCount.length > 30) maskCount.shift();
  if (PERSON.width !== S.vw || PERSON.height !== S.vh) { PERSON.width = S.vw; PERSON.height = S.vh; }
  PCTX.globalCompositeOperation = 'copy'; PCTX.drawImage(S.src, 0, 0, S.vw, S.vh);
  PCTX.globalCompositeOperation = 'destination-in'; PCTX.drawImage(MASK, 0, 0, S.vw, S.vh);
  PCTX.globalCompositeOperation = 'source-over';
  S.maskOk = true; S.maskT = performance.now();
  if (S.maskT - lightT > 500) { lightT = S.maskT; measureLight(); }
}
// How bright is the player, and is the cut-out steady? Used to brighten the player and to switch to the
// cartoon avatar when the room is too dark or the cut-out keeps breaking up.
function measureLight() {
  LUMA.width = 64; LUMA.height = 48;
  LCTX.clearRect(0, 0, 64, 48); LCTX.drawImage(PERSON, 0, 0, 64, 48);
  const d = LCTX.getImageData(0, 0, 64, 48).data; let sum = 0, n = 0;
  for (let i = 0; i < d.length; i += 4) if (d[i + 3] > 200) { sum += 0.299 * d[i] + 0.587 * d[i + 1] + 0.114 * d[i + 2]; n++; }
  const luma = n > 40 ? sum / n : null;
  const mean = maskCount.reduce((a, b) => a + b, 0) / (maskCount.length || 1);
  const jitter = mean ? Math.sqrt(maskCount.reduce((a, b) => a + (b - mean) ** 2, 0) / maskCount.length) / mean : 1;
  const L = S.light;
  if (luma != null) L.luma = L.luma == null ? luma : 0.7 * L.luma + 0.3 * luma;
  L.gain = L.luma ? clamp(135 / L.luma, 0.95, 1.7) : 1;        // auto-brighten a dim player
  const poor = (L.luma != null && L.luma < 42) || jitter > 0.35 || n <= 40;
  const now = performance.now();
  if (poor) { L.goodSince = null; L.poorSince = L.poorSince || now; } else { L.poorSince = null; L.goodSince = L.goodSince || now; }
  if (!L.avatar && L.poorSince && now - L.poorSince > 3000 && S.running) {
    L.avatar = true; caption(S.lang === 'en' ? 'The room is too dark for the camera cut-out - showing your avatar.' : '🧍');
  } else if (L.avatar && L.goodSince && now - L.goodSince > 3000) L.avatar = false;
}
let lastTs = 0;
// tests/demos: ?sim=1&cutout=1 sends the simulated player through the real camera cut-out path (mask smoothing,
// scene lighting, avatar fallback); &dark=1 makes the "room" dark and the mask patchy
const SIM_CUTOUT = Q.get('cutout') === '1', SIM_DARK = Q.get('dark') === '1';
function simMask() {
  const w = 160, h = 120, c = simMask.c || (simMask.c = document.createElement('canvas'));
  c.width = w; c.height = h; const x = c.getContext('2d', { willReadFrequently: true });
  x.clearRect(0, 0, w, h); x.drawImage(SIM.c, 0, 0, w, h);
  const d = x.getImageData(0, 0, w, h).data, out = new Float32Array(w * h);
  for (let i = 0; i < out.length; i++) {
    let v = d[i * 4 + 3] / 255;
    if (SIM_DARK) v = Math.random() < 0.5 ? v * Math.random() : v;      // a patchy cut-out, like a dark room
    else if (v === 0 && Math.random() < 0.02) v = 0.3;                    // faint "ghost" specks to clean away
    out[i] = v;
  }
  return { width: w, height: h, getAsFloat32Array: () => out };
}
function detect(now) {
  if (SIM) {
    if (SIM_CUTOUT) {
      try {
        if (SIM_DARK) { const x = SIM.c.getContext('2d'); x.globalCompositeOperation = 'source-atop'; x.fillStyle = 'rgba(0,0,0,0.82)'; x.fillRect(0, 0, SIM.c.width, SIM.c.height); x.globalCompositeOperation = 'source-over'; }
        updateMask(simMask());
      } catch (e) { /* ignore */ }
    }
    const lm = SIM.landmarks(now); S.worldRaw = SIM.world(lm); return lm;
  }
  if (!landmarker || S.src.readyState < 2) return null;
  const ts = Math.max(lastTs + 1, Math.round(now)); lastTs = ts;
  const t0 = performance.now(), r = landmarker.detectForVideo(S.src, ts);
  checkPoseSpeed(performance.now() - t0);
  try { if (r.segmentationMasks && r.segmentationMasks[0]) updateMask(r.segmentationMasks[0]); } catch (e) { S.maskOk = false; }
  try { if (r.segmentationMasks) r.segmentationMasks.forEach((m) => m.close && m.close()); } catch (e) { /* ignore */ }
  // 3D points in metres (z = towards the camera): Shadow Boxing reads forward punches from these
  S.worldRaw = r && r.worldLandmarks && r.worldLandmarks[0] ? r.worldLandmarks[0].map((p) => ({ x: p.x, y: p.y, z: p.z, v: p.visibility ?? 1 })) : null;
  return r && r.landmarks && r.landmarks[0] ? r.landmarks[0].map((p) => ({ x: p.x, y: p.y, v: p.visibility ?? 1 })) : null;
}
const WORLD_LIGHT = {        // the colour of each world's light, laid over the player so they look lit by the scene
  kabaddi: 'rgba(255,140,60,0.20)', jungle: 'rgba(120,200,110,0.16)', street: 'rgba(255,190,120,0.16)', lab: 'rgba(120,210,255,0.16)',
  stadium: 'rgba(120,160,255,0.24)', stage: 'rgba(244,114,182,0.20)', title: 'rgba(255,170,90,0.12)',
};
const LIT = document.createElement('canvas'), LITCTX = LIT.getContext('2d');
const FIG_IDS = [0, 2, 5, 11, 12, 13, 14, 15, 16, 23, 24, 25, 26, 27, 28];
function drawPlayer(g) {
  const o = V(0, 0), w = S.vw * V.s, h = S.vh * V.s;
  const live = S.view === 'camera' && S.maskOk && performance.now() - S.maskT < 600 && !S.light.avatar;
  const cutout = SIM && !SIM_CUTOUT ? SIM.c : live ? PERSON : null;
  g.save();
  g.globalAlpha = S.level && S.level.playerAlpha != null ? S.level.playerAlpha : 1;
  // soft shadow on the ground under the feet (full-body game)
  if (S.base && S.scope === 'full' && S.body && S.body.full && (!S.level || S.level.key !== 'pulse')) {
    const f = V(S.body.hipX, S.base.ankY), rx = 1.4 * S.base.sw * V.s;
    const sh = g.createRadialGradient(f.x, f.y, 0, f.x, f.y, rx);
    sh.addColorStop(0, 'rgba(0,0,0,0.38)'); sh.addColorStop(1, 'rgba(0,0,0,0)');
    g.save(); g.fillStyle = sh; g.beginPath(); g.ellipse(f.x, f.y + 4 * DPR, rx, rx * 0.22, 0, 0, Math.PI * 2); g.fill(); g.restore();
  }
  if (cutout) {
    let img = cutout;
    if (img === PERSON) {     // light the player like the scene: auto-brightness + the world's colour, only on the player's pixels
      if (LIT.width !== cutout.width || LIT.height !== cutout.height) { LIT.width = cutout.width; LIT.height = cutout.height; }
      LITCTX.globalCompositeOperation = 'copy';
      LITCTX.filter = `brightness(${S.light.gain.toFixed(2)}) contrast(1.06) saturate(1.12)`;
      LITCTX.drawImage(cutout, 0, 0); LITCTX.filter = 'none';
      LITCTX.globalCompositeOperation = 'source-atop';
      LITCTX.fillStyle = WORLD_LIGHT[S.world] || 'rgba(0,0,0,0)'; LITCTX.fillRect(0, 0, LIT.width, LIT.height);
      LITCTX.globalCompositeOperation = 'source-over';
      img = LIT;
    }
    g.translate(o.x + w, o.y); g.scale(-1, 1);
    g.shadowColor = 'rgba(255,255,255,0.55)'; g.shadowBlur = 5 * DPR;      // thin rim of light, not a thick glow
    g.drawImage(img, 0, 0, w, h);
  } else if (S.lm) {
    const P = {}; for (const i of FIG_IDS) P[i] = lmScreen(S.lm, i);
    ART.drawFigure(g, P, ART.PALETTE.player, { glowColor: '#22d3ee', alpha: g.globalAlpha });
    if (S.view === 'camera' && S.src) {          // cut-out not available: small mirror so the player still sees themselves
      const pw = Math.min(VIEW.W * 0.22, 260 * DPR), ph = pw * S.vh / S.vw, px = 14 * DPR, py = VIEW.H - ph - 90 * DPR;
      g.translate(px + pw, py); g.scale(-1, 1); g.drawImage(S.src, 0, 0, pw, ph);
      g.setTransform(1, 0, 0, 1, 0, 0); g.strokeStyle = '#fff'; g.lineWidth = 4; g.strokeRect(px, py, pw, ph);
    }
  }
  g.restore();
}

// ------------------------------------------------------------------ simulated player (tests + demos without a camera)
class SimPlayer {
  constructor() {
    this.c = document.createElement('canvas'); this.c.width = 640; this.c.height = 480; this.g = this.c.getContext('2d');
    this.dx = 0; this.lift = 0; this.move = 'neutral'; this.close = false; this.bpm = 80; this.run = 0; this.tw = []; this._anim = [];
    this.upper = Q.get('scope') === 'upper';      // demo of the upper-body game: sitting close, legs out of view
  }
  at(t, fn) { this.tw.push({ t, fn }); }
  tween(prop, to, t0, ms) { this.tw.push({ t: t0, fn: () => { this._anim.push({ prop, from: this[prop], to, t0, ms }); } }); }
  cue(kind, d) {
    const now = performance.now();
    if (kind === 'dodge') {
      const rt = rand(280, 480), right = Math.random() < 0.9;
      const dir = (d.side === 'L' ? 1 : -1) * (right ? 1 : -1);            // screen direction
      this.tween('dx', dir * 0.17, now + rt, 220); this.tween('dx', 0, now + rt + 1100, 300);
    } else if (kind === 'jump') {
      this.at(d.tArr - 230, () => { this.jumpT0 = performance.now(); });
    } else if (kind === 'bowler') {
      const p = { easy: 0.92, medium: 0.8, hard: 0.65 }[d.level], side = Math.random() < p ? d.target : (d.target === 'L' ? 'R' : 'L');
      this.tween('dx', (side === 'L' ? -1 : 1) * 0.12, d.tOcc + rand(350, 600), 220); this.tween('dx', 0, d.tOcc + 2300, 300);
    } else if (kind === 'combo') {
      const errs = [2, 1, 0, 0][d.tryIndex] ?? 0, seq = [...d.pattern];
      const idx = seq.map((_, i) => i).sort(() => Math.random() - 0.5).slice(0, errs);   // distinct steps to get wrong
      for (const i of idx) seq[i] = COMBO_MOVES.find((m) => m !== d.pattern[i] && m !== seq[i - 1] && m !== seq[i + 1]) || seq[i];
      let t = now + 900;
      for (const m of seq) { this.at(t, () => { this.move = m; }); t += 750; this.at(t, () => { this.move = 'neutral'; }); t += 500; }
    } else if (kind === 'close') { this.close = d.on; if (d.bpm) this.bpm = d.bpm; }
    else if (kind === 'escape') { this.runUntil = d.until; }
    else if (kind === 'fullbody') { this.at(now + 1500, () => { this.upper = false; }); }
    else if (kind === 'pad') {          // punch with the fist on the pad's side: mostly straight at the camera, sometimes a hook
      const rt = rand(250, 450), punch = { arm: d.side < 0 ? 'L' : 'R', kind: Math.random() < 0.7 ? 'forward' : 'side' };
      this.at(now + rt, () => { this.punch = punch; }); this.at(now + rt + 280, () => { this.punch = null; });
    }
  }
  step(now) {
    this.tw = this.tw.filter((x) => { if (now >= x.t) { x.fn(); return false; } return true; });
    for (const a of this._anim) { const u = clamp((now - a.t0) / a.ms, 0, 1); this[a.prop] = a.from + (a.to - a.from) * u; }
    this._anim = this._anim.filter((a) => now - a.t0 < a.ms + 50);
    this.lift = this.jumpT0 ? Math.max(0, Math.sin(clamp((now - this.jumpT0) / 450, 0, 1) * Math.PI)) * 0.15 : 0;
    this.run = this.runUntil && now < this.runUntil ? Math.sin(now / 1000 * 2 * Math.PI * 2.2) : 0;
  }
  landmarks(now) {
    this.step(now);
    const lm = Array.from({ length: 33 }, () => ({ x: 0.5, y: 0.5, v: 0.99 }));
    const set = (i, x, y, v = 0.99) => { lm[i] = { x: x - this.dx, y: y - this.lift, v }; };   // dx is a screen shift (mirrored)
    if (this.close) {           // face filling the ring
      set(0, 0.5, 0.45); set(2, 0.575, 0.38); set(5, 0.425, 0.38); set(1, 0.56, 0.38); set(4, 0.44, 0.38);
      set(11, 0.75, 0.85); set(12, 0.25, 0.85); for (const i of [13, 14, 15, 16, 23, 24, 25, 26, 27, 28]) set(i, 0.5, 1.2, 0.05);
      return lm;
    }
    const P = ART.movePose(this.move, { run: this.run });
    for (const k in P) set(+k, P[k][0], P[k][1]);
    if (this.upper) {                 // closer to the camera: zoom on the upper body, hips and legs out of view
      for (const k in P) { const x = (P[k][0] - 0.5) * 1.6 + 0.5, y = (P[k][1] - 0.3) * 1.6 + 0.36; set(+k, x, y, +k >= 23 ? 0.05 : 0.99); }
    }
    this.wz = {};
    if (this.punch) {                 // camera view: athlete's LEFT arm (11/13/15) is on the image's right (+x)
      const mx = (lm[11].x + lm[12].x) / 2, my = (lm[11].y + lm[12].y) / 2, sw = Math.abs(lm[11].x - lm[12].x);
      const [s, e, w, sg] = this.punch.arm === 'L' ? [11, 13, 15, 1] : [12, 14, 16, -1];
      if (this.punch.kind === 'side') {
        lm[w] = { x: mx + sg * 1.55 * sw, y: my, v: 0.99 }; lm[e] = { x: mx + sg * 1.05 * sw, y: my, v: 0.99 };
      } else {                        // straight at the camera: in the picture the fist stays in front of the shoulder
        lm[w] = { x: lm[s].x - sg * 0.15 * sw, y: lm[s].y - 0.05 * sw, v: 0.99 }; lm[e] = { x: lm[s].x - sg * 0.05 * sw, y: lm[s].y + 0.1 * sw, v: 0.99 };
        this.wz = { [e]: -0.27, [w]: -0.55 };
      }
    }
    return lm;
  }
  world(lm) {     // MediaPipe-style 3D points in metres (z towards the camera negative), from the 2D points + the punch depth
    if (!lm) return null;
    const k = 0.36 / Math.max(1, Math.abs(lm[11].x - lm[12].x) * 640), mx = (lm[11].x + lm[12].x) / 2 * 640, my = (lm[11].y + lm[12].y) / 2 * 480;
    return lm.map((p, i) => ({ x: (p.x * 640 - mx) * k, y: (p.y * 480 - my) * k, z: (this.wz && this.wz[i]) || 0, v: p.v }));
  }
  render(now) {   // the simulated "camera picture": a cartoon kid on a transparent background (the pulse reader samples its skin)
    const g = this.g; g.clearRect(0, 0, 640, 480);
    const beat = Math.sin(2 * Math.PI * (this.bpm / 60) * now / 1000);
    const skin = `rgb(${(200 * (1 + 0.004 * beat) + rand(-0.6, 0.6)).toFixed(2)},${(140 * (1 + 0.012 * beat) + rand(-0.6, 0.6)).toFixed(2)},${(120 * (1 + 0.002 * beat) + rand(-0.6, 0.6)).toFixed(2)})`;
    if (this.close) {
      const cx = 320 + this.dx * -640, cy = 0.42 * 480;
      g.fillStyle = '#16a34a'; g.beginPath(); g.ellipse(cx, 470, 230, 110, 0, Math.PI, 0); g.fill();
      g.fillStyle = skin; g.beginPath(); g.ellipse(cx, cy, 0.17 * 640, 0.26 * 480, 0, 0, Math.PI * 2); g.fill();
      g.fillStyle = '#1f1308'; g.beginPath(); g.ellipse(cx, cy - 0.235 * 480, 0.17 * 640, 0.06 * 480, 0, Math.PI, 0); g.fill();
      g.fillStyle = '#0f172a'; for (const ex of [0.575, 0.425]) { g.beginPath(); g.arc(ex * 640, 0.38 * 480, 9, 0, Math.PI * 2); g.fill(); }
      g.strokeStyle = '#7f1d1d'; g.lineWidth = 6; g.beginPath(); g.arc(cx, cy + 70, 40, 0.2 * Math.PI, 0.8 * Math.PI); g.stroke();
      return;
    }
    const lm = this.landmarks(now), P = {};
    for (const i of FIG_IDS) P[i] = { x: lm[i].x * 640, y: lm[i].y * 480 };
    ART.drawFigure(g, P, { ...ART.PALETTE.player, num: '', skin });
  }
}

// ------------------------------------------------------------------ main loop + drawing
const stage = $('stage'), G = stage.getContext('2d');
const LMF = new LandmarkFilter();
function resize() { DPR = window.devicePixelRatio || 1; stage.width = innerWidth * DPR; stage.height = innerHeight * DPR; }
addEventListener('resize', resize); resize();
function titleScene(g, W, H, groundY, now) {
  const t = now / 1000, beat = beatPulse(), boxH = H * 0.42, cx = W * 0.14;
  const move = ['hands_up', 'arms_out', 'hands_on_head', 'squat', 'left_hand_up', 'right_hand_up', 'hands_on_hips'][Math.floor(t / 0.9) % 7];
  const P = ART.movePose(move), Q2 = {};
  for (const k in P) Q2[k] = { x: cx + ((1 - P[k][0]) - 0.5) * boxH, y: groundY - (0.9 - P[k][1]) * boxH - beat * 8 * DPR };
  ART.drawFigure(g, Q2, ART.PALETTE.coach);
  const rx = W * 1.25 - ((t * 0.22) % 1.7) * W;
  ART.drawRunner(g, rx, groundY, H * 0.42, ART.PALETTE.raider, { dir: -1, phase: now / 55, lean: 0.42, reach: 1 });
  if (Math.random() < 0.3) ART.dust(rx + H * 0.06, groundY, 1);
}
// Where the camera picture goes on screen. Before calibration (and in the heart scan, where the face comes
// close) it simply fits the screen. During the game the player is placed in the world at a set size:
// full-body game - standing on the ground line, about 62 % of the screen tall, whatever their distance;
// upper-body game - a foreground player, waist at the bottom edge. Everything in the levels is drawn through
// the same mapping, so raiders, logs and pads stay exactly where the body is.
const BOWL_SIDE = 0.18, BOWLER_AT = 0.5;   // Read the Bowler: player's hips / bowler's run-up, as a share of the screen width
function placeView(W, H, dt) {
  const fit = Math.min(W / S.vw, H / S.vh);
  let s = fit, ox = (W - S.vw * fit) / 2, oy = (H - S.vh * fit) / 2;
  const free = !S.base || !S.running || (S.level && (S.level.key === 'pulse' || S.level.key === 'calib'));
  const crease = !free && S.level && S.level.key === 'bowler' && S.mode !== 'blind';
  if (crease && S.scope === 'full') {          // batsman's view: player small at the crease on the left, bowler free in the middle
    s = clamp((0.42 * H) / S.base.bodyPx, fit * 0.4, fit * 1.2);
    ox = BOWL_SIDE * W - S.base.hipX * s; oy = 0.95 * H - S.base.ankY * s;
  } else if (crease) {
    s = clamp(Math.min(0.1 * W, 0.15 * H) / S.base.sw, fit * 0.35, fit);
    ox = BOWL_SIDE * W - S.base.hipX * s; oy = 1.02 * H - S.base.hipY * s;
  } else if (!free && S.scope === 'full') {
    s = clamp((0.62 * H) / S.base.bodyPx, fit * 0.6, fit * 1.6);
    ox = W / 2 - S.base.hipX * s; oy = 0.9 * H - S.base.ankY * s;
  } else if (!free && S.scope === 'upper') {
    s = clamp(Math.min(0.18 * W, 0.26 * H) / S.base.sw, fit * 0.5, fit * 1.4);
    ox = W / 2 - S.base.hipX * s; oy = 1.02 * H - S.base.hipY * s;
  }
  const k = VIEW.ready ? Math.min(1, dt * 4) : 1;               // glide, don't jump, between levels
  VIEW.s += (s - VIEW.s) * k; VIEW.ox += (ox - VIEW.ox) * k; VIEW.oy += (oy - VIEW.oy) * k; VIEW.ready = true;
}
function frame(now) {
  requestAnimationFrame(frame);
  const dt = Math.min(0.05, (now - (S.lastNow || now)) / 1000); S.lastNow = now;
  const W = stage.width, H = stage.height;
  VIEW.W = W; VIEW.H = H;
  if (S.src) placeView(W, H, dt);
  if (S.src) {
    if (SIM) SIM.render(now);
    S.lmRaw = detect(now);
    S.lm = LMF.step(S.lmRaw, now);                       // smoothed points: steadier body, moves, avatar and pulse patch
    S.body = S.lm ? bodyInfo(S.lm) : null;
    S.bodyRaw = S.lmRaw ? bodyInfo(S.lmRaw) : null;      // raw points: reaction time, jump peak and punches (no lag at all)
    if (S.level && S.running) S.level.update(now);
    if (S.level && S.running && FULL_BODY_LEVELS.includes(S.level.key) && S.body && !S.body.full) {
      S.noFeet = S.noFeet || now;
      if (now - S.noFeet > 1200 && now - (S.feetSaid || 0) > 5000) { S.feetSaid = now; say(T('feet_hint'), { wait: false }); }
    } else S.noFeet = null;
  }
  ART.fxStep(dt);
  S.excite = Math.max(0, S.excite - dt * 0.7);
  S.dark += ((S.darkTarget || 0) - S.dark) * Math.min(1, dt * 14);
  const groundY = S.src && S.base ? groundLine() : S.src && S.body && S.body.full ? V(0, S.body.ankY).y : H * 0.9;
  G.save();
  if (ART.FX.shake) G.translate(rand(-1, 1) * ART.FX.shake, rand(-1, 1) * ART.FX.shake);
  ART.drawWorld(G, S.world, W, H, groundY, now / 1000, { excite: S.excite, scroll: S.scroll, dark: S.dark, beat: beatPulse() });
  if (!S.started) titleScene(G, W, H, groundY, now);
  if (S.level && S.level.drawBack) S.level.drawBack(G, V, now);
  if (S.src) drawPlayer(G);
  if (S.level) S.level.draw(G, V, now);
  ART.fxDraw(G, CANVAS_FONT);
  G.restore();
}

function aiChips() {
  const parts = [`SAM ${S.ai.sam === 'yes' ? '✓' : '·'}`, `Spark ${S.ai.spark === 'yes' ? '✓' : '·'}`, `Voice ${S.ai.voice === 'yes' ? '✓' : '·'}`];
  $('hud-ai').textContent = CFG.metaAvailable || CFG.aiAvailable ? 'AI: ' + parts.join(' ') : 'AI: offline';
}
setInterval(aiChips, 1000);
fetch('/api/arena/status').then((r) => r.json()).then((d) => {
  const chain = (d.ai && d.ai.chat_chain) || [];
  $('ai-status').textContent = d.meta_key ? `AI connected: ${chain.join(' → ')}.` :
    chain.length ? `AI coach and voice: ${chain.join(' → ')}. SAM calibration and the poster need the Meta API key.` :
    'No AI key on the server - the game still works; the coach, calibration, voice commands and poster use simple fallbacks.';
}).catch(() => {});

// ------------------------------------------------------------------ title screen controls
function setLang(l) {
  S.lang = I18N[l] ? l : 'en'; $('lang').value = S.lang; document.documentElement.lang = S.lang;
  document.querySelectorAll('.lang-btn').forEach((b) => b.classList.toggle('on', b.dataset.lang === S.lang));
}
document.querySelectorAll('.lang-btn').forEach((b) => b.addEventListener('click', () => { setLang(b.dataset.lang); audio(); sfx.coin(); }));
$('lang').addEventListener('change', () => setLang($('lang').value));
$('settings-btn').addEventListener('click', () => { const s = $('settings'); s.hidden = !s.hidden; $('settings-btn').setAttribute('aria-expanded', String(!s.hidden)); });
for (const k of ['mode', 'length', 'view', 'music']) if (Q.get(k) && [...$(k).options].some((o) => o.value === Q.get(k))) $(k).value = Q.get(k);
setLang(S.lang);
loadBoard();
document.querySelectorAll('.board-scope').forEach((b) => b.addEventListener('click', () => loadBoard(null, b.dataset.scope)));

// ------------------------------------------------------------------ bonus question (upper-body game -> full-body levels)
const BONUS = {
  open: false, _res: null,
  ask() {
    $('bonus-title').textContent = T('bonus_title'); $('bonus-text').textContent = T('bonus_text');
    $('bonus-yes').textContent = '✅ ' + T('bonus_yes'); $('bonus-no').textContent = '🏁 ' + T('bonus_no');
    $('bonus').hidden = false; this.open = true; sfx.levelUp(); $('bonus-yes').focus();
    say(T('bonus_say'), { wait: false });
    const auto = S.sim ? (Q.get('bonus') === '0' ? false : true) : null;
    return new Promise((resolve) => {
      this._res = resolve;
      if (auto !== null) setTimeout(() => this.answer(auto), 1500);
      this._to = setTimeout(() => this.answer(false), 45000);       // nobody answered: show the results
    });
  },
  answer(yes) {
    if (!this.open) return;
    this.open = false; clearTimeout(this._to); $('bonus').hidden = true; sfx.ok();
    const r = this._res; this._res = null; if (r) r(!!yes);
  },
};
$('bonus-yes').addEventListener('click', () => BONUS.answer(true));
$('bonus-no').addEventListener('click', () => BONUS.answer(false));

// ------------------------------------------------------------------ the game
const FINAL_SCAN = { en: 'FINAL SCAN', hi: 'आख़िरी स्कैन', te: 'చివరి స్కాన్' };
async function showIntro(key, label) {
  const L = I18N[S.lang] || I18N.en;
  $('intro-num').textContent = label; $('intro-icon').textContent = LEVEL_META[key].icon;
  $('intro-title').textContent = L.titles[key]; $('intro-measure').textContent = L.measures[key];
  const goal = key === 'bowler' && S.mode === 'blind' ? T('bowler_blind_intro') : T(key + '_intro');
  $('intro-goal').textContent = goal; $('count').innerHTML = ''; $('intro').hidden = false;
  $('hud-level').textContent = L.titles[key]; textTrial('');
  sfx.levelUp();
  await Promise.all([say(goal), sleep(FAST ? 200 : 2600)]);
  for (const n of ['3', '2', '1']) { $('count').innerHTML = `<span class="n">${n}</span>`; sfx.count(); await sleep(FAST ? 60 : 700); }
  $('count').classList.add('go'); $('count').innerHTML = '<span class="n">GO!</span>'; sfx.go(); await sleep(FAST ? 60 : 450);
  $('intro').hidden = true; $('count').classList.remove('go');
}
async function showClear(key, before) {
  const pf = pointsFor(rawPayload()), lv = pf.levels[key] || { points: 0, stars: 1 };
  S.points = pf.total; updateScore(false);
  const L = I18N[S.lang] || I18N.en, r = S.raw;
  const stat = {
    dodge: () => { const ok = r.dodge.filter((t) => t.ok), rts = ok.map((t) => t.rt).filter(Boolean); return `${ok.length}/${r.dodge.length} · ⚡ ${rts.length ? Math.min(...rts) : '–'} ms`; },
    jump: () => { const hs = r.jump.filter((j) => j.ok).map((j) => j.cm); return `${hs.length}/${r.jump.length} · ⬆ ${hs.length ? Math.round(Math.max(...hs)) : 0} cm`; },
    escape: () => `👟 ${r.escape ? r.escape.steps : 0}`,
    boxing: () => `🥊 ${r.boxing ? r.boxing.hits : 0}`,
    pulse: () => { const p = r.pulse[r.pulse.length - 1]; return p && p.bpm ? `❤ ${p.bpm} bpm` : '❤ –'; },
    bowler: () => `${r.bowler.filter((t) => t.answer === t.target).length}/${r.bowler.length} 🏏`,
    combo: () => `✗ ${r.combo.tries.map((t) => editDistance(r.combo.pattern, t.done).dist).join(' → ')}`,
  }[key];
  $('clear-title').textContent = L.clear; $('clear-pts').textContent = '+' + Math.max(0, pf.total - before).toLocaleString('en-IN');
  $('clear-stat').textContent = stat ? stat() : '';
  const spans = $('clear-stars').children;
  for (let i = 0; i < 3; i++) { spans[i].className = ''; spans[i].style.animationDelay = `${0.25 + i * 0.25}s`; }
  $('clear').hidden = false; sfx.levelUp();
  for (let i = 0; i < 3; i++) setTimeout(() => { if (i < lv.stars) { spans[i].className = 'on'; sfx.star(i); } }, FAST ? 0 : 250 + i * 250);
  if (lv.stars === 3) ART.confetti(VIEW.W, VIEW.H, 80);
  await sleep(FAST ? 300 : 2400);
  $('clear').hidden = true;
}
function setWorld(world, music) {
  S.world = world;
  if (SOUND.music && S.mode !== 'blind') playMusic(music || world); else stopMusic();
}
async function startGame() {
  if (S.started) return;
  S.started = true; $('start-error').textContent = ''; $('start-btn').disabled = true; $('start-btn').textContent = '📷 …';
  S.lang = $('lang').value; S.mode = $('mode').value; S.quick = $('length').value === 'quick'; S.view = $('view').value;
  SOUND.music = $('music').value === 'on' && S.mode !== 'blind';
  document.body.className = 'mode-' + S.mode; document.documentElement.lang = S.lang;
  const h = parseFloat($('pheight').value); if (h >= 100 && h <= 230) CFG.heightCm = h;
  audio(); setMuted(false);
  try {
    if (S.sim) { SIM = new SimPlayer(); S.src = SIM.c; S.vw = 640; S.vh = 480; }
    else { await startCamera(); $('start-btn').textContent = '🧠 …'; await loadPose(); }
  } catch (e) {
    S.started = false; S.src = null; $('start-btn').disabled = false; $('start-btn').textContent = '▶ PLAY';
    $('start-error').textContent = 'Could not start: ' + (e && e.message ? e.message : e) + '. Allow the camera, use Chrome/Edge/Safari, or watch the demo player.';
    return;
  }
  $('title').hidden = true; $('hud').hidden = false; S.running = true; updateScore(false);
  const plan = Object.assign({ raider_window_ms: 1500, log_speed: 1, bowler_hard_share: 0.35, combo_length: 4 }, S.plan); S.plan = plan;
  const N = S.quick ? { dodge: 6, jump: 3, escape: 10, pulse: 12, bowler: 6, tries: 2, boxing: 20 }
                    : { dodge: 10, jump: 5, escape: 15, pulse: 15, bowler: 8, tries: 3, boxing: 30 };
  // 1. what can the camera see? whole body -> full game; only the waist up -> upper-body game
  setWorld('kabaddi', 'kabaddi');
  await play(new Calibrate('auto'));
  const full = [
    { key: 'dodge', mk: () => new Dodge(N.dodge, plan.raider_window_ms) }, { key: 'jump', mk: () => new Jump(N.jump, plan.log_speed) },
    { key: 'escape', mk: () => new Escape(N.escape) }, { key: 'pulse', mk: () => new Pulse(N.pulse, 0) },
    { cal: 'stadium', kind: 'full' }, { key: 'bowler', mk: () => new Bowler(N.bowler, plan.bowler_hard_share) },
    { key: 'combo', mk: () => new Combo(plan.combo_length, N.tries) }, { key: 'pulse', mk: () => new Pulse(N.pulse, 1), final: true },
  ];
  const upper = [
    { key: 'boxing', mk: () => new Boxing(N.boxing) }, { key: 'pulse', mk: () => new Pulse(N.pulse, 0) },
    { cal: 'stadium', kind: 'upper' }, { key: 'bowler', mk: () => new Bowler(N.bowler, plan.bowler_hard_share) },
    { key: 'combo', mk: () => new Combo(plan.combo_length, N.tries) }, { key: 'pulse', mk: () => new Pulse(N.pulse, 1), final: true },
  ];
  const bonus = [
    { cal: 'kabaddi', kind: 'full', cue: true }, { key: 'dodge', mk: () => new Dodge(N.dodge, plan.raider_window_ms) },
    { key: 'jump', mk: () => new Jump(N.jump, plan.log_speed) }, { key: 'escape', mk: () => new Escape(N.escape) },
  ];
  const runSteps = async (steps, total, prefix) => {
    let no = 0;
    for (const st of steps) {
      if (S.quit) return;
      if (st.cal) {
        setWorld(st.cal, st.cal);
        if (st.cue) SIM && SIM.cue('fullbody', {});
        if (await play(new Calibrate(st.kind, st.cue ? 40000 : 0)) === false) return;
        continue;
      }
      const meta = LEVEL_META[st.key];
      setWorld(meta.world, meta.music);
      await showIntro(st.key, st.final ? FINAL_SCAN[S.lang] : `${prefix || T('level')} ${++no}/${total}`);
      if (S.quit) return;
      S.streak = 0; setCombo(0); const before = S.points;
      await play(st.mk());
      if (S.quit) return;
      await showClear(st.key, before);
    }
  };
  if (!S.quit && S.scope === 'upper') {
    await runSteps(upper, 4);
    if (!S.quit && await BONUS.ask()) await runSteps(bonus, 3, 'BONUS');
  } else if (!S.quit) {
    await runSteps(full, 6);
  }
  finishGame();
}
$('start-btn').addEventListener('click', startGame);
try { document.fonts.load('40px Bungee'); document.fonts.load('800 20px "Baloo 2"'); } catch (e) { /* older browser */ }
requestAnimationFrame(frame);
if (Q.get('autostart') === '1') setTimeout(startGame, 300);
window.__arena = S;   // for automated tests
