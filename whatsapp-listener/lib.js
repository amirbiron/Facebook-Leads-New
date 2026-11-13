// לוגיקה טהורה של המאזין — בלי רשת, בלי דיסק, בלי מצב גלובלי.
// כל החלטה שמשפיעה על החשבון (האם להתחבר שוב, האם לעצור, האם למחוק סשן)
// וכל החלטה על הודעה (האם היא מקבוצה במעקב, האם כבר נספרה) עוברת דרך
// פונקציה כאן, ולכן יש לה בדיקה שנכשלת אם הלוגיקה משתנה.
//
// בסיס: myAgent (whatsapp-listener/lib.js, קומיט 3e9ab16), כפי שמתועד ב-Ck
// ב"חילוץ-חיבור-וואטסאפ-myAgent.md", סעיף 11. מה שהועתק כמו שהוא מסומן.

import { createHash, timingSafeEqual } from 'node:crypto';

// ===== סוגי הודעה =====

// ממפה את מפתח התוכן של הודעת Baileys (מה ש-getContentType מחזיר על תוכן
// שעבר normalizeMessageContent) לסוג, ומחלץ את הטקסט. רשימה מותרת
// (fail-closed): רק תוכן שאדם כתב. הודעות פרוטוקול, תגובות אימוג'י, סקרים
// ואירועי מערכת מקבלים type=null ולא נספרים.
// שמות השדות לפי WAProto של @whiskeysockets/baileys@7.0.0-rc14
// (WAProto/index.d.ts: conversation, IExtendedTextMessage.text, caption של
// image/video/document, IAudioMessage.ptt). הועתק מ-myAgent.
export function mapContent(contentKey, content) {
  const c = content || {};
  switch (contentKey) {
    case 'conversation':
      return { type: 'chat', text: c.conversation || '' };
    case 'extendedTextMessage':
      return { type: 'chat', text: c.extendedTextMessage?.text || '' };
    case 'imageMessage':
      return { type: 'image', text: c.imageMessage?.caption || '' };
    case 'videoMessage':
      return { type: 'video', text: c.videoMessage?.caption || '' };
    case 'audioMessage':
      return { type: c.audioMessage?.ptt ? 'ptt' : 'audio', text: '' };
    case 'stickerMessage':
      return { type: 'sticker', text: '' };
    case 'documentMessage':
      return { type: 'document', text: c.documentMessage?.caption || '' };
    case 'locationMessage':
    case 'liveLocationMessage':
      return { type: 'location', text: '' };
    case 'contactMessage':
      return { type: 'vcard', text: '' };
    case 'contactsArrayMessage':
      return { type: 'multi_vcard', text: '' };
    default:
      return { type: null, text: '' };
  }
}

// אורך טקסט בתווים (code points, לא יחידות UTF-16) — כדי שאמוג'י ייספר כתו אחד.
export function textLength(text) {
  return typeof text === 'string' ? Array.from(text).length : 0;
}

// ===== מזהים =====

// מספר טלפון (ספרות בלבד, בפורמט בינלאומי בלי +) מתוך המזהה הראשון שהוא
// מזהה טלפון. מזהה LID לא מכיל מספר, ולכן לא נוגעים בו — Baileys מעביר את
// המספר האמיתי, כשהוא ידוע, בשדה נפרד (participantAlt בקבוצה:
// lib/Utils/decode-wa-message.js:187). ההתאמה מעוגנת על כל המחרוזת: בליסטנר
// הישן של myAgent ביטוי לא מעוגן "מצא" מספר ישראלי בתוך 42% ממזהי LID
// אקראיים (Ck, סעיף 7). הועתק מ-myAgent.
export function phoneFromJids(...jids) {
  for (const jid of jids) {
    if (typeof jid !== 'string') continue;
    const m = jid.match(/^(\d+)(?::\d+)?@(s\.whatsapp\.net|c\.us)$/);
    if (m && /^\d{6,15}$/.test(m[1])) return m[1];
  }
  return null;
}

// מזהה קבוצה: ספרות (ובקבוצות ותיקות גם מקף) ואחריהן @g.us. Baileys מזהה
// קבוצה לפי הסיומת בלבד (isJidGroup = endsWith('@g.us'),
// lib/WABinary/jid-utils.js:71) ובונה את המזהה מ-attrs.id של השרת
// (lib/Socket/groups.js:302) — לכן התבנית לא מניחה יותר מספרות ומקפים.
const GROUP_JID_RE = /^[0-9][0-9-]*@g\.us$/;

// רשימת הקבוצות שבמעקב, ממשתנה סביבה מופרד בפסיקים (או רווחים/שורות).
// מקבל גם מזהה בלי @g.us (נוח להעתקה מהטאבלט) ומשלים אותו. ערך לא תקין
// לא מפיל את העלייה — הוא מוחזר ב-invalid כדי שייכתב ללוג.
export function parseGroupIds(raw) {
  const ids = new Set();
  const invalid = [];
  if (typeof raw !== 'string') return { ids, invalid };
  for (const part of raw.split(/[\s,]+/)) {
    const token = part.trim();
    if (!token) continue;
    const jid = token.includes('@') ? token : `${token}@g.us`;
    if (GROUP_JID_RE.test(jid)) ids.add(jid);
    else invalid.push(token);
  }
  return { ids, invalid };
}

// מחרוזת חיצונית (שם קבוצה, הודעת שגיאה מהשרת) לשורת לוג אחת: בלי תווי
// שליטה ושבירות שורה — שם קבוצה עם \n היה מזייף שורות לוג — ובאורך חסום.
export function oneLine(value, max = 120) {
  const s = String(value ?? '')
    .replace(/[\u0000-\u001f\u007f\u2028\u2029]+/g, ' ')
    .trim();
  return s.length > max ? `${s.slice(0, max - 1)}…` : s;
}

// ===== הודעה מקבוצה =====

// בונה רשומה מהודעת Baileys, או מחזיר null כשזו לא הודעה שאדם כתב בקבוצה.
// helpers = { normalizeMessageContent, getContentType, toNumber } מ-Baileys —
// מוזרקים כדי שהקובץ יישאר טהור, ובבדיקות עוברות הפונקציות האמיתיות.
// השדות לפי Ck סעיף 11.6: הקבוצה מ-key.remoteJid, השולח מ-key.participant
// ו-key.participantAlt, השם מ-pushName, הזמן מ-toNumber(messageTimestamp)
// (יכול להגיע כ-Long). הרשומה כוללת את השולח והטקסט כי שלב 3 יעביר אותם
// הלאה; בשלב הזה הם לא נכתבים ללוג (פרטיות — K7 ב-CLAUDE.md).
export function toGroupRecord(msg, upsertType, helpers) {
  const key = msg && msg.key;
  if (!key || key.fromMe) return null;
  const groupId = key.remoteJid;
  if (typeof groupId !== 'string' || !groupId.endsWith('@g.us')) return null;
  if (typeof key.id !== 'string' || !key.id) return null;

  const content = helpers.normalizeMessageContent(msg.message);
  const contentKey = helpers.getContentType(content);
  const { type, text } = mapContent(contentKey, content);
  if (!type) return null;

  const ts = helpers.toNumber(msg.messageTimestamp);
  return {
    messageId: key.id,
    groupId,
    senderJid: typeof key.participant === 'string' ? key.participant : null,
    senderPhone: phoneFromJids(key.participant, key.participantAlt),
    senderName: typeof msg.pushName === 'string' ? msg.pushName : null,
    type,
    text,
    timestampSec: Number.isFinite(ts) && ts > 0 ? ts : null,
    offline: upsertType === 'append',
  };
}

// מפתח מניעת הכפילויות: key.id בתוך הקבוצה. המזהה של קבוצה תמיד בצורת
// @g.us (אין לו צורת LID), כך שאותה הודעה ב-notify וב-append מקבלת אותו מפתח.
export function dedupKey(record) {
  return `${record.groupId}|${record.messageId}`;
}

// ===== סגירת חיבור: מה עושים =====

// קודי סגירה, לפי @whiskeysockets/baileys@7.0.0-rc14: lib/Types/index.js
// (DisconnectReason) ו-lib/Defaults/index.js (UNAUTHORIZED_CODES = [401, 403, 419]).
// הספרייה עצמה לא משתמשת ב-UNAUTHORIZED_CODES ולא מזהה חסימה — זה נשאר לנו.
// הקוד מגיע מ-CB:failure (attrs.reason) או מ-CB:stream:error (attrs.code),
// ושניהם מגיעים ל-connection.update עם lastDisconnect.error.output.statusCode
// (lib/Socket/socket.js:791-801). הועתק מ-myAgent.
export const CODES = {
  loggedOut: 401,
  forbidden: 403,
  unauthorized419: 419,
  connectionReplaced: 440,
  multideviceMismatch: 411,
  restartRequired: 515,
  timedOut: 408,
};

// ההודעה שהספרייה שמה כשנגמרו קודי ה-QR בלי שמישהו סרק
// (lib/Socket/socket.js:716, קוד 408).
export const QR_EXPIRED_MESSAGE = 'QR refs attempts ended';

// מה עושים אחרי שהחיבור נסגר. מחזיר { action, kind }:
//   reconnect       — להתחבר שוב דרך מתזמן ההשהיה הגדלה (אף פעם לא מיד)
//   relink          — הקישור בוטל: למחוק סשן, להתריע, ולחכות לסריקת QR
//   stop            — לעצור ולהתריע; אין חיבור אוטומטי עד הפעלה מחדש
//   pairing_expired — QR לא נסרק בזמן: לחזור להמתנה, בלי חיבור חדש
// 403 עוצר ולא מוחק: אחרי חסימה לא רוצים לולאה של מחיקת סשן ו-QR חדש.
// linked = לסשן יש creds.me — הסימן ש-Baileys עצמו בודק כדי להחליט בין login
// לרישום (lib/Socket/socket.js:320). לא creds.registered: הוא הופך ל-true רק
// בקישור בקוד, ונשאר false אחרי סריקת QR. הועתק מ-myAgent.
export function classifyDisconnect({ statusCode, message, linked }) {
  const msg = String(message || '');
  if (statusCode === CODES.forbidden) return { action: 'stop', kind: 'blocked' };
  if (statusCode === CODES.loggedOut || statusCode === CODES.unauthorized419) {
    return { action: 'relink', kind: 'logged_out' };
  }
  if (statusCode === CODES.connectionReplaced) return { action: 'stop', kind: 'replaced' };
  if (statusCode === CODES.multideviceMismatch) return { action: 'stop', kind: 'stopped' };
  if (!linked && statusCode === CODES.timedOut && msg.includes(QR_EXPIRED_MESSAGE)) {
    return { action: 'pairing_expired', kind: null };
  }
  return { action: 'reconnect', kind: null };
}

// ===== השהיה גדלה =====

// כל חיבור מחדש מופיע בטלפון כאירוע, ולכן אין מסלול שמתחבר מיד: 3s, 6s,
// 12s ... עד תקרה של 5 דקות, ואחרי MAX ניסיונות רצופים בלי חיבור פתוח —
// עוצרים ומתריעים (gave_up). הועתק מ-myAgent.
export const RECONNECT_MIN_DELAY_MS = 3000;
export const RECONNECT_MAX_DELAY_MS = 5 * 60 * 1000;
export const RECONNECT_MAX_ATTEMPTS = 8;

export function backoffDelayMs(attempt) {
  const n = Math.max(1, Math.floor(attempt));
  return Math.min(RECONNECT_MAX_DELAY_MS, RECONNECT_MIN_DELAY_MS * 2 ** (n - 1));
}

// ===== השהיה בעלייה (בין הפעלות של התהליך) =====

// אם התהליך קורס ו-Render מפעיל אותו מחדש, ההשהיה שבזיכרון מתאפסת וכל
// הפעלה הייתה מתחברת מיד. לכן זמני העלייה נשמרים בדיסק, וכל עלייה שבאה מהר
// אחרי עליות קודמות מחכה לפי אותה השהיה גדלה. הועתק מ-myAgent.
export const STARTUP_WINDOW_MS = 15 * 60 * 1000;
const STARTUP_HISTORY_MAX = 20;
// כמה עליות קודמות בחלון נחשבות "לולאת קריסה" שמצדיקה התראה. עלייה אחת
// קודמת היא deploy רגיל; שתיים ומעלה ב-15 דקות כבר אינן מקרה.
export const CRASH_LOOP_PREVIOUS_STARTS = 2;

export function pruneStarts(starts, nowMs) {
  const list = Array.isArray(starts) ? starts.filter((t) => Number.isFinite(t)) : [];
  return list.filter((t) => nowMs - t >= 0 && nowMs - t < STARTUP_WINDOW_MS).slice(-STARTUP_HISTORY_MAX);
}

export function startupDelayMs(previousStarts, nowMs) {
  const recent = pruneStarts(previousStarts, nowMs).length;
  return recent === 0 ? 0 : backoffDelayMs(recent);
}

// ===== טוקן לדף ה-QR =====

// אורך מינימלי לטוקן. הדף מאפשר לקשר מכשיר לחשבון, ולכן טוקן קצר (שאפשר
// לנחש) גרוע מדף כבוי. 24 תווים אקראיים הם מעל 140 ביט.
export const QR_TOKEN_MIN_LENGTH = 24;

// השוואה בזמן קבוע. משווים hash של שני הצדדים כדי שגם אורך שונה לא יחשוף
// מידע (timingSafeEqual דורש אורכים זהים). טוקן ריק אף פעם לא תקף.
// הועתק מ-myAgent.
export function safeTokenEqual(presented, expected) {
  if (typeof presented !== 'string' || typeof expected !== 'string') return false;
  if (!presented || !expected) return false;
  const a = createHash('sha256').update(presented, 'utf8').digest();
  const b = createHash('sha256').update(expected, 'utf8').digest();
  return timingSafeEqual(a, b);
}

// ===== שומר על אובייקט החיבור =====

// המאזין רק קורא. Baileys לא שולחת מעצמה אישור קריאה, "מקליד" או הודעה —
// כל אלה יוצאים רק מקריאה מפורשת לפונקציה של החיבור (Ck, סעיף 11.7). לכן
// הקוד שלנו מקבל את החיבור רק דרך העטיפה הזו, שמתירה רשימה סגורה של
// מאפיינים, וכל השאר זורק לפני שמשהו נשלח. רשימה מותרת ולא אסורה:
// פונקציה חדשה שתתווסף לספרייה חסומה מעצמה.
// הפנימיים של Baileys לא עוברים דרך העטיפה (הם קוראים זה לזה בתוך closure),
// ולכן אישורי המסירה האוטומטיים לא מושפעים.
export const SOCKET_ALLOWED_PROPS = Object.freeze(['ev', 'groupFetchAllParticipating', 'end']);

export class ForbiddenSocketAccess extends Error {
  constructor(prop) {
    super(`גישה אסורה לחיבור וואטסאפ: "${String(prop)}" — המאזין קורא בלבד`);
    this.name = 'ForbiddenSocketAccess';
  }
}

export function guardSocket(sock) {
  const allowed = new Set(SOCKET_ALLOWED_PROPS);
  return new Proxy(sock, {
    get(target, prop) {
      if (typeof prop === 'string' && allowed.has(prop)) {
        const value = target[prop];
        return typeof value === 'function' ? value.bind(target) : value;
      }
      // then נבדק על כל אובייקט שעובר דרך await; Symbol-ים נבדקים ע"י Node
      // בהדפסה. שניהם קריאות של הסביבה, לא של הקוד שלנו — מחזירים undefined.
      if (prop === 'then' || typeof prop === 'symbol') return undefined;
      throw new ForbiddenSocketAccess(prop);
    },
    set(_target, prop) {
      throw new ForbiddenSocketAccess(prop);
    },
  });
}

// ===== זמן מקומי =====

// בדיקה שאזור הזמן מוכר ל-Intl. ערך לא תקין לא מפיל את העלייה (U3).
export function isValidTimeZone(tz) {
  try {
    new Intl.DateTimeFormat('en-US', { timeZone: tz });
    return true;
  } catch {
    return false;
  }
}

function partsInZone(ms, timeZone) {
  const parts = new Intl.DateTimeFormat('en-GB', {
    timeZone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).formatToParts(new Date(ms));
  const get = (type) => parts.find((p) => p.type === type)?.value;
  return { y: get('year'), mo: get('month'), d: get('day'), h: get('hour'), mi: get('minute') };
}

// תאריך מקומי בצורת YYYY-MM-DD — המפתח של היום בסיכום היומי.
export function localDayKey(ms, timeZone) {
  const p = partsInZone(ms, timeZone);
  return `${p.y}-${p.mo}-${p.d}`;
}

// שעה מקומית בצורת HH:MM.
export function localTime(ms, timeZone) {
  const p = partsInZone(ms, timeZone);
  return `${p.h}:${p.mi}`;
}

// ===== מונים יומיים ומניעת כפילויות =====

// כמה זמן זוכרים מזהה של הודעה שנספרה. Baileys שולחת אישור מסירה לפני שהיא
// משדרת את ההודעה (lib/Socket/messages-recv.js:1417-1432), כך שכפילות
// מגיעה זמן קצר אחרי המקור: הודעה שהגיעה ריקה (stub) ופוענחה בבקשה חוזרת,
// או מסירה חוזרת אחרי ניתוק. שלושה ימים הם מרווח רחב לזה.
export const SEEN_TTL_MS = 3 * 24 * 60 * 60 * 1000;
// תקרה על מספר המזהים, כדי שהקובץ והזיכרון יישארו חסומים גם בתעבורה כבדה.
export const SEEN_MAX = 20000;

function isPlainObject(v) {
  return v !== null && typeof v === 'object' && !Array.isArray(v);
}

function cleanCounter(v) {
  const count = Number.isFinite(v?.count) && v.count >= 0 ? Math.floor(v.count) : 0;
  const withText = Number.isFinite(v?.withText) && v.withText >= 0 ? Math.floor(v.withText) : 0;
  return { count, withText: Math.min(withText, count) };
}

function cleanCounters(obj) {
  const out = {};
  if (!isPlainObject(obj)) return out;
  for (const [id, v] of Object.entries(obj)) out[id] = cleanCounter(v);
  return out;
}

export function emptyStats(dayKey) {
  return { version: 1, day: dayKey, since: dayKey, daily: {}, totals: {}, seen: {} };
}

// טוען מצב מהדיסק אחרי ולידציה: קובץ ישן, חלקי או ידני לא מפיל את השירות
// ולא מכניס NaN למונים. מה שלא תקין מתאפס.
export function normalizeStats(raw, todayKey) {
  if (!isPlainObject(raw) || raw.version !== 1) return emptyStats(todayKey);
  const dayRe = /^\d{4}-\d{2}-\d{2}$/;
  const day = typeof raw.day === 'string' && dayRe.test(raw.day) ? raw.day : todayKey;
  const since = typeof raw.since === 'string' && dayRe.test(raw.since) ? raw.since : day;
  const seen = {};
  if (isPlainObject(raw.seen)) {
    for (const [k, t] of Object.entries(raw.seen)) if (Number.isFinite(t)) seen[k] = t;
  }
  return { version: 1, day, since, daily: cleanCounters(raw.daily), totals: cleanCounters(raw.totals), seen };
}

// תפיסה אטומית של מזהה: בדיקה והכנסה באותה פעולה סינכרונית, בלי await
// ביניהן. ב-Node כל הקוד הזה רץ על thread אחד, ולכן שתי הגעות של אותה הודעה
// לא יכולות לעבור את הבדיקה שתיהן. מחזיר true רק לתופס הראשון.
export function claimMessage(stats, key, nowMs) {
  if (Object.prototype.hasOwnProperty.call(stats.seen, key)) return false;
  stats.seen[key] = nowMs;
  return true;
}

export function pruneSeen(stats, nowMs) {
  const entries = Object.entries(stats.seen).filter(([, t]) => nowMs - t < SEEN_TTL_MS);
  entries.sort((a, b) => a[1] - b[1]);
  stats.seen = Object.fromEntries(entries.slice(-SEEN_MAX));
}

export function recordMessage(stats, groupId, hasText) {
  for (const bucket of [stats.daily, stats.totals]) {
    const c = bucket[groupId] || (bucket[groupId] = { count: 0, withText: 0 });
    c.count += 1;
    if (hasText) c.withText += 1;
  }
}

// מעבר יום: מחזיר את סיכום היום שנגמר (או null אם עוד אותו יום) ומאפס את
// המונים היומיים. המצטבר (totals) לא מתאפס — הוא מה שנותן תמונה של שבוע
// גם כשהלוגים הישנים כבר נמחקו (ב-Render, Hobby שומר לוגים 7 ימים).
export function rollDay(stats, todayKey) {
  if (stats.day === todayKey) return null;
  const summary = { day: stats.day, since: stats.since, daily: stats.daily, totals: stats.totals };
  stats.day = todayKey;
  stats.daily = {};
  return summary;
}

function sumCounters(obj) {
  let count = 0;
  let withText = 0;
  for (const c of Object.values(obj)) {
    count += c.count;
    withText += c.withText;
  }
  return { count, withText };
}

// שורת הסיכום היומי. כל הקבוצות שבמעקב מופיעות, גם עם 0 — קבוצה שותקת היא
// מידע. שמות מהמטמון, אחרת המזהה.
export function formatDailySummary(summary, monitoredIds, nameOf, { late = false } = {}) {
  const ids = new Set([...monitoredIds, ...Object.keys(summary.daily)]);
  const day = sumCounters(summary.daily);
  const total = sumCounters(summary.totals);
  const perGroup = [...ids]
    .map((id) => {
      const d = summary.daily[id] || { count: 0, withText: 0 };
      const t = summary.totals[id] || { count: 0, withText: 0 };
      return { id, d, t };
    })
    .sort((a, b) => b.d.count - a.d.count || b.t.count - a.t.count)
    .map(({ id, d, t }) => `${oneLine(nameOf(id) || id, 40)}: ${d.count} (מצטבר ${t.count})`)
    .join(' | ');
  return (
    `📊 סיכום יומי ${summary.day}${late ? ' (נכתב באיחור — השירות לא רץ במעבר היום)' : ''}: ` +
    `${day.count} הודעות, ${day.withText} עם טקסט` +
    ` | מצטבר מאז ${summary.since}: ${total.count} הודעות, ${total.withText} עם טקסט` +
    (perGroup ? ` || ${perGroup}` : ' || אין קבוצות במעקב')
  );
}
