// קבצי מצב קטנים על הדיסק הקבוע (JSON). כתיבה אטומית: לקובץ זמני ואז
// rename, כדי שקריסה באמצע כתיבה (OOM, deploy) לא תשאיר קובץ חצוי — הלקח
// מ-myAgent, שבו פרופיל שנכתב חלקית הכניס את השירות ללולאה (Ck, סעיף 4).
// rename באותה תיקייה הוא אטומי ב-POSIX.

import fs from 'node:fs';
import path from 'node:path';

// טעינת קובץ מצב, עם שלושה מקרים שאסור לבלבל ביניהם:
//   missing  — הקובץ לא קיים: מתחילים ריק, ומותר לכתוב.
//   corrupt  — הקובץ קיים אבל אינו JSON תקין: מזיזים אותו הצידה
//              (<file>.corrupt-<זמן>) כדי לא למחוק ראיה, ומתחילים ריק.
//   unreadable — הקובץ קיים ולא נקרא (EACCES, EIO, EMFILE...): ייתכן שהוא
//              תקין לגמרי. מחזירים writable=false — הקורא לא כותב עליו,
//              אחרת הכתיבה הבאה הייתה דורסת מונים ומזהים שלא נקראו.
// אותו כלל גם כשההזזה הצידה נכשלת: לא דורסים קובץ שלא הצלחנו לשמור.
// מחזיר { value, status, writable }. לא זורק.
export function loadJsonState(file, log, nowMs = Date.now()) {
  let raw;
  try {
    raw = fs.readFileSync(file, 'utf8');
  } catch (err) {
    if (err.code === 'ENOENT') return { value: null, status: 'missing', writable: true };
    log.error(`❌ לא הצלחתי לקרוא את ${file} (${err.name}: ${err.code || err.message}) — לא אכתוב עליו, כדי לא לדרוס תוכן שלא נקרא.`);
    return { value: null, status: 'unreadable', writable: false };
  }
  try {
    return { value: JSON.parse(raw), status: 'ok', writable: true };
  } catch (err) {
    const aside = `${file}.corrupt-${nowMs}`;
    try {
      fs.renameSync(file, aside);
    } catch (moveErr) {
      log.error(
        `❌ הקובץ ${file} פגום ולא הצלחתי להזיז אותו הצידה (${moveErr.name}: ${moveErr.code || moveErr.message}) — לא אכתוב עליו.`,
      );
      return { value: null, status: 'unreadable', writable: false };
    }
    log.warn(`⚠️ הקובץ ${file} פגום (${err.name}) — הועבר ל-${aside}, ומתחיל ממצב ריק.`);
    return { value: null, status: 'corrupt', writable: true };
  }
}

// כתיבה סינכרונית ואטומית. זורקת בכשל — הקורא מחליט אם ואיך לרשום (K11).
export function writeJsonAtomic(file, value) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const tmp = `${file}.${process.pid}.tmp`;
  fs.writeFileSync(tmp, JSON.stringify(value));
  fs.renameSync(tmp, file);
}
