// קבצי מצב קטנים על הדיסק הקבוע (JSON). כתיבה אטומית: לקובץ זמני ואז
// rename, כדי שקריסה באמצע כתיבה (OOM, deploy) לא תשאיר קובץ חצוי — הלקח
// מ-myAgent, שבו פרופיל שנכתב חלקית הכניס את השירות ללולאה (Ck, סעיף 4).
// rename באותה תיקייה הוא אטומי ב-POSIX.

import fs from 'node:fs';
import path from 'node:path';

// מחזיר את התוכן, או null כשהקובץ חסר. קובץ פגום מוחזר כ-null עם אזהרה
// בלוג — לא מפיל את השירות.
export function readJson(file, log) {
  let raw;
  try {
    raw = fs.readFileSync(file, 'utf8');
  } catch (err) {
    if (err.code !== 'ENOENT') log.warn(`לא הצלחתי לקרוא את ${file}: ${err.name}: ${err.message}`);
    return null;
  }
  try {
    return JSON.parse(raw);
  } catch (err) {
    log.warn(`הקובץ ${file} פגום (${err.name}: ${err.message}) — מתחיל ממצב ריק.`);
    return null;
  }
}

// כתיבה סינכרונית ואטומית. זורקת בכשל — הקורא מחליט אם ואיך לרשום (K11).
export function writeJsonAtomic(file, value) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const tmp = `${file}.${process.pid}.tmp`;
  fs.writeFileSync(tmp, JSON.stringify(value));
  fs.renameSync(tmp, file);
}
