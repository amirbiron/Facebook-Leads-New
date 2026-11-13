// לוגר שמועבר ל-Baileys במקום pino. ב-Baileys יש עשרות קריאות warn/error
// שמעבירות מזהי שולח (jid, sender, from, participant ב-key) ואת הצומת הגולמי
// של ההודעה (node) — למשל lib/Utils/decode-wa-message.js:288-296
// ('failed to decrypt message' עם key, sender, author). רמת לוג לא פותרת את
// זה: אלה בדיוק השגיאות שרוצים לראות. לכן הלוגר הזה נכשל-סגור (K7, K13):
//   - מאובייקט הנתונים יוצאים רק שדות מרשימה מותרת, ושגיאות רק בתקציר
//     (סוג, הודעה, קוד). כל שדה אחר נשמט, ורק **שמו** נרשם, כדי שיהיה ברור
//     שהיה שם משהו;
//   - כל טקסט חופשי (ההודעה, הודעת השגיאה, ה-stack) עובר scrubIdentifiers,
//     שמחליף מזהי וואטסאפ ומספרים ארוכים בסימון;
//   - שדות ה-child (bindings) מסוננים באותה רשימה.
// הממשק לפי lib/Utils/logger.d.ts של 7.0.0-rc14 (ILogger): level, child(obj),
// ו-trace/debug/info/warn/error(obj, msg?). Baileys בודקת גם logger.level
// ישירות (lib/Socket/socket.js: logger.level === 'debug').

import { oneLine, scrubIdentifiers } from './lib.js';

const LEVELS = { trace: 10, debug: 20, info: 30, warn: 40, error: 50, fatal: 60, silent: Infinity };

// שדות שמותר להדפיס כמו שהם — מונים, סוגים ושמות פנימיים של Baileys, בלי
// מזהים ובלי תוכן. ערך מחרוזת עדיין עובר scrubIdentifiers.
const ALLOWED_FIELDS = new Set([
  'class',
  'type',
  // לא 'name': ב-lib/Socket/socket.js:847 הוא pushName — השם האישי של החשבון
  'version',
  'count',
  'attempts',
  'statusCode',
  'reason',
  'errorCode',
  'messageType',
  'isSessionRecordError',
  'offlineNotifs',
  'retryCount',
]);
const ERROR_FIELDS = new Set(['err', 'error']);

function summarizeError(err) {
  if (!err || typeof err !== 'object') return scrubIdentifiers(oneLine(err, 300));
  const parts = [err.name || err.constructor?.name || 'Error'];
  if (err.message) parts.push(scrubIdentifiers(oneLine(err.message, 300)));
  const status = err.output && err.output.statusCode;
  if (status) parts.push(`status=${status}`);
  if (err.code) parts.push(`code=${scrubIdentifiers(String(err.code))}`);
  return parts.join(': ');
}

function scalar(value) {
  if (value === null || typeof value === 'number' || typeof value === 'boolean') return value;
  if (typeof value === 'string') return scrubIdentifiers(oneLine(value, 200));
  return undefined; // אובייקט או מערך בשדה מותר — לא נכנסים פנימה
}

// מחזיר { fields, dropped } — מה שמותר להדפיס, ושמות השדות שנשמטו.
export function sanitizeFields(obj) {
  const fields = {};
  const dropped = [];
  if (!obj || typeof obj !== 'object') return { fields, dropped };
  for (const [key, value] of Object.entries(obj)) {
    if (ERROR_FIELDS.has(key)) {
      fields[key] = summarizeError(value);
    } else if (key === 'trace' && typeof value === 'string') {
      // trace = error.stack אצל Baileys. השורה הראשונה מספיקה לאבחון.
      fields.trace = scrubIdentifiers(oneLine(value.split('\n')[0], 300));
    } else if (ALLOWED_FIELDS.has(key) && scalar(value) !== undefined) {
      fields[key] = scalar(value);
    } else {
      dropped.push(key);
    }
  }
  return { fields, dropped };
}

export function createSafeLogger({ level = 'warn', write = (line) => console.log(line), bindings = {} } = {}) {
  const threshold = LEVELS[level] ?? LEVELS.warn;
  const effectiveLevel = LEVELS[level] !== undefined ? level : 'warn';
  const { fields: boundFields } = sanitizeFields(bindings);

  function emit(lvl, objOrMsg, msg) {
    if (LEVELS[lvl] < threshold) return;
    let obj = objOrMsg;
    let text = msg;
    if (typeof objOrMsg === 'string') {
      obj = undefined;
      text = objOrMsg;
    } else if (objOrMsg instanceof Error) {
      obj = { err: objOrMsg };
    }
    const { fields, dropped } = sanitizeFields(obj);
    const record = {
      level: lvl,
      ...boundFields,
      msg: scrubIdentifiers(oneLine(text ?? '', 300)),
      ...fields,
    };
    if (dropped.length) record.dropped = dropped.join(',');
    write(`[baileys] ${JSON.stringify(record)}`);
  }

  return {
    level: effectiveLevel,
    child(obj) {
      return createSafeLogger({ level: effectiveLevel, write, bindings: { ...bindings, ...(obj || {}) } });
    },
    trace: (o, m) => emit('trace', o, m),
    debug: (o, m) => emit('debug', o, m),
    info: (o, m) => emit('info', o, m),
    warn: (o, m) => emit('warn', o, m),
    error: (o, m) => emit('error', o, m),
    fatal: (o, m) => emit('fatal', o, m),
  };
}
