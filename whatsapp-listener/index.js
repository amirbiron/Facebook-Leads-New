// מאזין קריאה-בלבד לקבוצות וואטסאפ — שלב 2: מקבל הודעות מקבוצות שבמעקב,
// רושם ללוג (קבוצה, שעה, אורך — בלי התוכן) וסופר אותן. לא מעביר שום דבר
// הלאה ולא שולח דבר לוואטסאפ. שלב 3 יחבר אותו לצינור הסיווג של FB Leads.
//
// עובד עם Baileys (@whiskeysockets/baileys@7.0.0-rc14), שמדברת עם שרתי וואטסאפ
// ישירות ב-WebSocket, בלי דפדפן. בסיס: הליסטנר של myAgent, שרץ עליה
// בפרודקשן (Ck, "חילוץ-חיבור-וואטסאפ-myAgent.md", סעיף 11).
//
// הקובץ הזה רק מחבר: משתני סביבה, Baileys, דיסק, HTTP, טיימרים. ההחלטות
// נמצאות ב-lib.js וב-listener.js ונבדקות ב-test/.

import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import pino from 'pino';
import QRCode from 'qrcode';
import makeWASocket, {
  getContentType,
  makeCacheableSignalKeyStore,
  normalizeMessageContent,
  toNumber,
  useMultiFileAuthState,
} from '@whiskeysockets/baileys';

import {
  CRASH_LOOP_PREVIOUS_STARTS,
  isValidTimeZone,
  localDayKey,
  normalizeStats,
  parseGroupIds,
  pruneStarts,
  QR_TOKEN_MIN_LENGTH,
  safeTokenEqual,
  startupDelayMs,
} from './lib.js';
import { createListener, safeJson } from './listener.js';
import { createNotifier } from './telegram.js';
import { readJson, writeJsonAtomic } from './store.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const log = {
  info: (...a) => console.log(...a),
  warn: (...a) => console.warn(...a),
  error: (...a) => console.error(...a),
};

// ===== Config =====

// מספר שלם חיובי ממשתנה סביבה. ערך לא תקין נופל לברירת המחדל עם אזהרה
// (NaN עובר כל השוואה בשקט). הועתק מ-myAgent.
function positiveIntFromEnv(name, fallback) {
  const raw = process.env[name];
  if (raw === undefined || raw === '') return fallback;
  const value = Number(raw);
  if (Number.isInteger(value) && value > 0) return value;
  log.warn(`⚠️ ${name}="${raw}" אינו מספר שלם חיובי — משתמש ב-${fallback}.`);
  return fallback;
}

// Render מזריק PORT (ברירת מחדל 10000, https://render.com/docs/web-services).
const PORT = positiveIntFromEnv('PORT', 3001);
// ברירת המחדל היא localhost (K5 ב-CLAUDE.md); Render דורש 0.0.0.0, ולכן
// render.yaml מגדיר HOST=0.0.0.0 במפורש.
const HOST = (process.env.HOST || '').trim() || '127.0.0.1';
// תיקיית הסשן של Baileys (קובצי JSON קטנים). ב-Render על הדיסק הקבוע;
// מקומית — יחסית לתיקיית השירות ולא ל-CWD.
const AUTH_DIR = path.resolve(__dirname, process.env.WA_AUTH_DIR || '.baileys_auth');
// ליד תיקיית הסשן ולא בתוכה, כדי שמחיקת סשן (401) לא תאפס אותם.
const STARTS_FILE = path.join(path.dirname(AUTH_DIR), 'wa-listener-starts.json');
const STATS_FILE = path.join(path.dirname(AUTH_DIR), 'wa-listener-stats.json');

const rawQrToken = process.env.QR_ACCESS_TOKEN || '';
// טוקן קצר מדי גרוע מדף כבוי: מי שמנחש אותו יכול לקשר את החשבון שלו לשירות.
const QR_ACCESS_TOKEN = rawQrToken.length >= QR_TOKEN_MIN_LENGTH ? rawQrToken : '';
if (!rawQrToken) {
  log.warn('⚠️ QR_ACCESS_TOKEN לא הוגדר — דף /qr כבוי, ולא ניתן לקשר מכשיר.');
} else if (!QR_ACCESS_TOKEN) {
  log.warn(`⚠️ QR_ACCESS_TOKEN קצר מ-${QR_TOKEN_MIN_LENGTH} תווים — דף /qr כבוי. צריך ערך אקראי ארוך.`);
}

const { ids: GROUP_IDS, invalid: invalidGroups } = parseGroupIds(process.env.WA_GROUP_IDS || '');
for (const bad of invalidGroups) log.warn(`⚠️ ערך לא תקין ב-WA_GROUP_IDS, מדולג: "${bad}"`);
if (GROUP_IDS.size === 0) {
  // לא "רשימה ריקה = הכל": המשימה היא מעקב אחרי קבוצות שנבחרו. בלי רשימה
  // השירות רק מתחבר וכותב את רשימת הקבוצות, כדי שיהיה ממה לבחור.
  log.warn('⚠️ WA_GROUP_IDS ריק — אף קבוצה לא במעקב. רשימת הקבוצות של החשבון תיכתב ללוג אחרי ההתחברות.');
} else {
  log.info(`🎯 ${GROUP_IDS.size} קבוצות במעקב.`);
}

const rawTz = process.env.TIMEZONE || 'Asia/Jerusalem';
const TIME_ZONE = isValidTimeZone(rawTz) ? rawTz : 'Asia/Jerusalem';
if (TIME_ZONE !== rawTz) log.warn(`⚠️ TIMEZONE="${rawTz}" לא מוכר — משתמש ב-${TIME_ZONE}.`);

// זהות המכשיר המקושר, כפי שהיא מוצגת בטלפון (הגדרות ← מכשירים מקושרים).
// נקבעת פעם אחת ולא משתנה: כל שינוי נראה לוואטסאפ כמו מכשיר חדש. זהה
// לברירת המחדל של 7.0.0-rc14 (Browsers.macOS('Chrome') =
// ['Mac OS', 'Chrome', '14.4.1'], lib/Utils/browser-utils.js:18) ולערך של
// myAgent — כתוב במפורש כדי ששדרוג של הספרייה לא ישנה אותו בשקט.
const BROWSER = ['Mac OS', 'Chrome', '14.4.1'];

// גרסת WhatsApp Web שהמאזין מציג: ערך קבוע, לא fetchLatestWaWebVersion בכל
// התחברות. זו הגרסה שמגיעה עם 7.0.0-rc14 (lib/Defaults/index.js:5) וזו שרצה
// ב-myAgent. משנים רק יחד עם שדרוג מכוון של הספרייה.
const WA_WEB_VERSION = [2, 3000, 1043857760];

// לוג של הספרייה (pino, JSON). ברירת מחדל warn, כדי שהלוג לא יוצף.
const logger = pino({ level: process.env.BAILEYS_LOG_LEVEL || 'warn' });

const notifier = createNotifier({
  token: process.env.TELEGRAM_BOT_TOKEN || '',
  chatId: process.env.TELEGRAM_CHAT_ID || '',
  log,
});
if (!notifier.enabled) {
  log.error('⚠️ TELEGRAM_BOT_TOKEN או TELEGRAM_CHAT_ID חסרים — התראות על חסימה וניתוק ייכתבו רק ללוג.');
}

// כתובת דף ה-QR להתראות — בלי הטוקן. טוקן לא נשלח לשום מקום.
// RENDER_EXTERNAL_URL מוזרק אוטומטית ע"י Render.
const QR_HINT = process.env.RENDER_EXTERNAL_URL ? `${process.env.RENDER_EXTERNAL_URL}/qr?token=<QR_ACCESS_TOKEN>` : '';

// ===== מונים ומניעת כפילויות — על הדיסק =====
// נשמרים בדיסק ולא רק בזיכרון: מונה יומי שמתאפס ב-restart לא נותן מדידה
// (הלקח של באג #18 ב-CLAUDE.md), וגם מניעת הכפילויות צריכה לשרוד restart —
// הודעות שהצטברו בזמן ההשבתה מגיעות מיד אחריו.
const stats = normalizeStats(readJson(STATS_FILE, log), localDayKey(Date.now(), TIME_ZONE));
let persistTimer = null;

function flushStats() {
  if (persistTimer) {
    clearTimeout(persistTimer);
    persistTimer = null;
  }
  try {
    writeJsonAtomic(STATS_FILE, stats);
  } catch (err) {
    log.error(`❌ שמירת המונים נכשלה (${STATS_FILE}): ${err.name}: ${err.message}`);
  }
}

// כתיבה מרוכזת: הודעות שמגיעות ברצף נשמרות בכתיבה אחת, עד 2 שניות אחרי.
function persistStats() {
  if (persistTimer) return;
  persistTimer = setTimeout(flushStats, 2000);
}

// ===== מחיקת סשן =====
// רק אחרי שהקישור בוטל (401/419). אחרי חסימה (403) לא מוחקים.
function purgeAuth() {
  try {
    fs.rmSync(AUTH_DIR, { recursive: true, force: true });
    log.info(`🗑️ נמחקה תיקיית הסשן ${AUTH_DIR} — הקישור הבא דרך /qr.`);
  } catch (err) {
    log.error(`❌ כשל במחיקת תיקיית הסשן ${AUTH_DIR}: ${err.name}: ${err.message}`);
  }
}

const listener = createListener({
  groupIds: GROUP_IDS,
  timeZone: TIME_ZONE,
  qrHint: QR_HINT,
  loadAuth: () => useMultiFileAuthState(AUTH_DIR),
  makeSocket: (auth) =>
    makeWASocket({
      version: WA_WEB_VERSION,
      browser: BROWSER,
      auth: { creds: auth.state.creds, keys: makeCacheableSignalKeyStore(auth.state.keys, logger) },
      logger,
      // לא להציג את החשבון כ"זמין" בכל התחברות. עם false הספרייה שולחת
      // 'unavailable' כשהחיבור נפתח (lib/Socket/chats.js:1065), ואישורי המסירה
      // יוצאים מסוג inactive (lib/Socket/messages-recv.js:1413-1414).
      markOnlineOnConnect: false,
    }),
  purgeAuth,
  toQrDataUrl: (qr) => QRCode.toDataURL(qr, { width: 400, margin: 2 }),
  notifier,
  stats,
  persistStats,
  helpers: { normalizeMessageContent, getContentType, toNumber },
  timers: { setTimeout, clearTimeout },
  now: () => Date.now(),
  log,
});

// ===== HTTP: דף QR מאחורי טוקן =====
function page(title, body, refreshSec) {
  return (
    '<!doctype html><html dir="rtl" lang="he"><head><meta charset="utf-8">' +
    '<meta name="viewport" content="width=device-width, initial-scale=1">' +
    (refreshSec ? `<meta http-equiv="refresh" content="${refreshSec}">` : '') +
    `<title>${title}</title></head>` +
    '<body style="font-family:sans-serif;text-align:center;padding:40px 16px;background:#0b1020;color:#e6e9f2;">' +
    body +
    '</body></html>'
  );
}

function handleQr(res, url) {
  // בלי טוקן מוגדר, או עם טוקן שגוי — 404, כאילו הדף לא קיים
  if (!QR_ACCESS_TOKEN || !safeTokenEqual(url.searchParams.get('token') || '', QR_ACCESS_TOKEN)) {
    res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' });
    res.end('not found');
    return;
  }
  const html = (title, body, refreshSec) => {
    res.writeHead(200, {
      'Content-Type': 'text/html; charset=utf-8',
      'Cache-Control': 'no-store',
      // הטוקן בכתובת — שלא ייצא ב-Referer (בדף אין משאבים חיצוניים, אבל ליתר ביטחון)
      'Referrer-Policy': 'no-referrer',
    });
    res.end(page(title, body, refreshSec));
  };
  const { runtime } = listener;

  if (runtime.state === 'open') {
    html('וואטסאפ — מחובר', '<h2>המאזין מחובר</h2><p>אין צורך בסריקה.</p>');
    return;
  }
  if (runtime.state === 'stopped') {
    html(
      'וואטסאפ — עצר',
      `<h2>המאזין עצר (${runtime.stopKind || ''})</h2><p>פרטים בלוג ובטלגרם. אחרי הבדיקה — הפעלה מחדש של השירות ב-Render.</p>`,
    );
    return;
  }
  if (runtime.linked) {
    html('וואטסאפ — מתחבר', '<h2>יש סשן מקושר והמאזין מתחבר</h2><p>אין צורך בסריקה. הדף מתרענן.</p>', 10);
    return;
  }
  if (runtime.qrDataUrl) {
    html(
      'וואטסאפ — סרוק QR',
      '<h1>סרוק את הקוד מהוואטסאפ</h1>' +
        '<p>הגדרות ← מכשירים מקושרים ← קישור מכשיר</p>' +
        `<img src="${runtime.qrDataUrl}" alt="WhatsApp QR" style="background:white;padding:16px;border-radius:8px;max-width:100%;" />` +
        '<p style="opacity:.6;font-size:13px;margin-top:24px;">הדף מתרענן כל 20 שניות (ה-QR מתחלף).</p>',
      20,
    );
    return;
  }
  // אין QR עדיין: פותחים חיבור לקישור (אם ממתינים לקישור) ומבקשים לרענן
  listener.requestPairing();
  html('וואטסאפ — מכין QR', '<h2>מכין QR…</h2><p>הדף יתרענן בעוד רגע.</p>', 3);
}

const server = http.createServer((req, res) => {
  let url;
  try {
    url = new URL(req.url || '/', 'http://localhost');
  } catch {
    res.writeHead(400);
    res.end();
    return;
  }
  if (url.pathname === '/qr') {
    handleQr(res, url);
    return;
  }
  // כל השאר: בדיקת חיים בלבד, בלי מידע על החשבון או על המצב. המצב מוצג
  // בדף /qr, מאחורי הטוקן.
  res.writeHead(200, { 'Content-Type': 'text/plain; charset=utf-8' });
  res.end('ok');
});

// ===== שגיאות לא מטופלות =====
// unhandledRejection: נרשם ולא מפיל. יציאה הייתה גורמת ל-Render להפעיל מחדש
// ולהתחבר שוב — כל חיבור כזה הוא אירוע בטלפון. ניתוק אמיתי מגיע ממילא דרך
// connection.update ועובר במתזמן החיבור. (myAgent)
process.on('unhandledRejection', (reason) => {
  log.error('⚠️ unhandledRejection:', reason && reason.stack ? reason.stack : safeJson(reason));
});

// uncaughtException: הסטאק נפרם באמצע קוד סינכרוני ומצב התהליך לא מוגדר,
// ולכן יוצאים — אחרי שמירת המונים. ההפעלה הבאה מחכה לפי startupDelayMs,
// ואם זה חוזר — מתריעה על לולאת קריסה. (myAgent)
process.on('uncaughtException', (err) => {
  log.error('❌ uncaughtException — יוצא:', err && err.stack ? err.stack : safeJson(err));
  flushStats();
  process.exit(1);
});

// כיבוי מסודר (deploy / restart ב-Render): שומרים, סוגרים את החיבור, יוצאים.
let shuttingDown = false;
function shutdown(signal) {
  if (shuttingDown) return;
  shuttingDown = true;
  log.info(`👋 ${signal} — שומר מונים, סוגר את החיבור ויוצא.`);
  flushStats();
  listener.shutdown();
  setTimeout(() => process.exit(0), 1000).unref();
}
process.on('SIGTERM', () => shutdown('SIGTERM'));
process.on('SIGINT', () => shutdown('SIGINT'));

// ===== מעקב זיכרון =====
// בלי דפדפן אין תהליכי בן, ולכן RSS של התהליך קרוב לכל הזיכרון של השירות
// (Ck 11.1). בכל זאת נמדדת גם המכולה מ-cgroup, כמו ב-FB Leads (באג #20):
// זה המספר ש-Render מציג ושלפיו ה-kernel מחליט על OOM. מה לא ידוע עדיין
// (Ck 11.10): כמה זיכרון נצרך לאורך ימים ועם הרבה קבוצות — לכן הלוג הזה.
const CGROUP_PATHS = [
  ['/sys/fs/cgroup/memory.current', '/sys/fs/cgroup/memory.max'],
  ['/sys/fs/cgroup/memory/memory.usage_in_bytes', '/sys/fs/cgroup/memory/memory.limit_in_bytes'],
];

function containerMemMb() {
  for (const [usagePath, limitPath] of CGROUP_PATHS) {
    let usage;
    try {
      usage = Number(fs.readFileSync(usagePath, 'utf8').trim()) / 1024 / 1024;
    } catch {
      continue; // הנתיב הזה לא קיים בגרסת ה-cgroup הזו — מנסים את הבא
    }
    if (!Number.isFinite(usage)) continue;
    let limit = null;
    try {
      const raw = fs.readFileSync(limitPath, 'utf8').trim();
      const parsed = raw === 'max' ? NaN : Number(raw) / 1024 / 1024;
      // cgroup v1 מסמן "ללא הגבלה" במספר ענק
      if (Number.isFinite(parsed) && parsed < 1_000_000) limit = parsed;
    } catch {
      // תקרה לא קריאה — מדווחים שימוש בלי אחוז
    }
    return { usage, limit };
  }
  return null;
}

const MEMORY_LOG_INTERVAL_MS = 5 * 60 * 1000;
setInterval(() => {
  const mem = process.memoryUsage();
  const mb = (n) => Math.round(n);
  const c = containerMemMb();
  const container = c
    ? `מכולה ${mb(c.usage)}MB${c.limit ? ` (${Math.round((c.usage / c.limit) * 100)}% מהתקרה)` : ''}, `
    : '';
  log.info(
    `📊 זיכרון: ${container}RSS ${mb(mem.rss / 1048576)}MB, heap ${mb(mem.heapUsed / 1048576)}/${mb(mem.heapTotal / 1048576)}MB, מצב=${listener.runtime.state}`,
  );
  if (c && c.limit && c.usage / c.limit > 0.85) log.warn('⚠️ זיכרון המכולה מעל 85% מהתקרה.');
}, MEMORY_LOG_INTERVAL_MS).unref();

// ===== סיכום יומי =====
// אם השירות לא רץ במעבר היום — הסיכום של היום הקודם נכתב עכשיו, באיחור.
listener.dailyTick({ late: true });
setInterval(() => listener.dailyTick(), 60 * 1000).unref();

// ===== עלייה =====
server.listen(PORT, HOST, () => log.info(`🌐 שרת HTTP על ${HOST}:${PORT}`));

const startNow = Date.now();
const previousStarts = pruneStarts(readJson(STARTS_FILE, log)?.starts, startNow);
try {
  writeJsonAtomic(STARTS_FILE, { starts: [...previousStarts, startNow] });
} catch (err) {
  log.warn(`⚠️ לא הצלחתי לכתוב את ${STARTS_FILE} — ההשהיה בין הפעלות לא תישמר: ${err.name}: ${err.message}`);
}
if (previousStarts.length >= CRASH_LOOP_PREVIOUS_STARTS) {
  void listener.alert('crash_loop', null, `${previousStarts.length + 1} עליות ב-15 הדקות האחרונות`);
}
const initialDelay = startupDelayMs(previousStarts, startNow);
if (initialDelay > 0) {
  log.info(`⏳ עליות קודמות היו לאחרונה — מחכה ${Math.round(initialDelay / 1000)}s לפני חיבור.`);
}
setTimeout(() => {
  listener.startSocket('startup').catch((err) => {
    listener.logError('❌ פתיחת חיבור בעלייה נכשלה:', err);
    listener.scheduleReconnect('startup failed');
  });
}, initialDelay);
