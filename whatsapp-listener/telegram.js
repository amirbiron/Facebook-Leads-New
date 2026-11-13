// התראות לטלגרם, ישירות ל-API, דרך אותו בוט של FB Leads (TELEGRAM_BOT_TOKEN
// ו-TELEGRAM_CHAT_ID), בלי לגעת בקוד של FB Leads.
//
// טלגרם דורש את הטוקן בנתיב הכתובת: https://api.telegram.org/bot<token>/METHOD_NAME
// (https://core.telegram.org/bots/api#making-requests). ב-FB Leads הכתובת הזו
// דלפה ללוגים דרך הודעות שגיאה (באג #24 ב-CLAUDE.md). לכן כאן, כמו שם:
//   - הכתובת עם הטוקן נבנית רק בפונקציה אחת בקובץ הזה;
//   - כל שגיאה יוצאת כהודעה מנוקה, בלי החריגה המקורית (לא כ-cause), כי היא
//     עלולה להחזיק את הכתובת — למשל "Failed to parse URL from <url>";
//   - הניקוי נכשל-סגור: אם נשאר זכר לחלק הסודי, מחזירים הודעה קבועה.
// ההודעות נשלחות כטקסט רגיל, בלי parse_mode, כך שתוכן חיצוני (הודעת שגיאה
// מהשרת של וואטסאפ) לא יכול לשבור עיצוב (באג #23).

const TELEGRAM_API_BASE = 'https://api.telegram.org';
// מגבלת טלגרם לטקסט הודעה: 1-4096 תווים (https://core.telegram.org/bots/api#sendmessage).
const TELEGRAM_TEXT_MAX = 4096;
const REDACTED = '<TOKEN>';

// מסיר את הטוקן ואת מקטע /bot<token> מכל טקסט. החלק הסודי הוא מה שאחרי
// הנקודתיים (<bot_id>:<secret>); אם הוא עדיין מופיע אחרי ההחלפה — מוותרים על
// כל הטקסט.
export function redactToken(text, token) {
  const s = String(text ?? '');
  if (!token) return s;
  let out = s.split(`/bot${token}`).join(`/bot${REDACTED}`).split(token).join(REDACTED);
  const secret = token.includes(':') ? token.slice(token.indexOf(':') + 1) : token;
  if (secret && out.includes(secret)) out = '[הודעת השגיאה הוסתרה — הכילה את טוקן הבוט]';
  return out;
}

export class TelegramSendError extends Error {
  constructor(message, { status = null } = {}) {
    super(message);
    this.name = 'TelegramSendError';
    this.status = status;
  }
}

// שולח הודעה. מחזיר את גוף התשובה של טלגרם בהצלחה; כל כשל — רשת, timeout,
// סטטוס שאינו 2xx, או ok:false — זורק TelegramSendError עם הודעה מנוקה.
// fetchImpl מוזרק לבדיקות.
export async function telegramSendMessage({ token, chatId, text, fetchImpl = fetch, timeoutMs = 15000 }) {
  let failure = null;
  let status = null;
  let body = null;
  try {
    const url = `${TELEGRAM_API_BASE}/bot${token}/sendMessage`;
    const res = await fetchImpl(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ chat_id: chatId, text: String(text).slice(0, TELEGRAM_TEXT_MAX) }),
      signal: AbortSignal.timeout(timeoutMs),
    });
    status = res.status;
    body = await res.json().catch(() => null);
    if (!res.ok || !body || body.ok !== true) {
      const description = body && typeof body.description === 'string' ? body.description : '';
      failure = `HTTP ${res.status}${description ? ` — ${description}` : ''}`;
    }
  } catch (err) {
    // רק שם וההודעה, אחרי ניקוי. החריגה עצמה לא נשמרת ולא נזרקת הלאה.
    const name = (err && err.name) || 'Error';
    const cause = err && err.cause && err.cause.message ? ` (${err.cause.message})` : '';
    failure = `${name}: ${(err && err.message) || ''}${cause}`;
  }
  // החריגה החדשה נבנית רק מהמחרוזת המנוקה, בלי cause. ב-JS אין שרשור
  // אוטומטי (כמו __context__ בפייתון, שהדליף את הטוקן ב-FB Leads), אבל
  // הזריקה נשארת מחוץ ל-catch כדי שאף עריכה עתידית לא תצרף את המקורית.
  if (failure !== null) throw new TelegramSendError(redactToken(failure, token), { status });
  return body;
}

// מתריע ששולח לטלגרם, או רק כותב ללוג כשהטוקן או הצ'אט חסרים. אף פעם לא
// זורק: התראה שנכשלה נרשמת בלוג — אין מקום אחר לדווח אליו.
// מחזיר true רק כשטלגרם אישר את ההודעה (K11 — הקורא יכול לבדוק).
export function createNotifier({ token, chatId, fetchImpl, log, timeoutMs }) {
  const enabled = Boolean(token && chatId);
  return {
    enabled,
    async send(text) {
      if (!enabled) {
        log.error(`⚠️ התראה לא נשלחה (TELEGRAM_BOT_TOKEN או TELEGRAM_CHAT_ID חסרים): ${text}`);
        return false;
      }
      try {
        await telegramSendMessage({ token, chatId, text, fetchImpl, timeoutMs });
        return true;
      } catch (err) {
        log.error(`⚠️ שליחת התראה לטלגרם נכשלה: ${redactToken(err && err.message, token)}`);
        return false;
      }
    },
  };
}
