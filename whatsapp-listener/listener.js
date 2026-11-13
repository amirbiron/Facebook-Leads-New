// ליבת המאזין: מחזור החיים של החיבור וקבלת הודעות. כל תופעת לוואי — רשת,
// דיסק, טיימרים, טלגרם — מוזרקת מבחוץ (index.js), כדי שהבדיקות יפעילו את
// הקוד הזה דרך אותם אירועים ש-Baileys משדרת (connection.update,
// messages.upsert), ולא דרך פונקציות פנימיות.
//
// בסיס: index.js של myAgent (קומיט 3e9ab16, Ck סעיף 11.11), בלי כל מה ששולח:
// בלי בלוק התשובה, בלי humanDelay, בלי onMessagesUpdate (הגבלת 463 מגיעה רק
// על הודעה שנשלחה), ועם הסינון הפוך — קבוצות פנימה, פרטיות החוצה (Ck 11.7).

import {
  backoffDelayMs,
  claimMessage,
  classifyDisconnect,
  dedupKey,
  formatDailySummary,
  guardSocket,
  localDayKey,
  localTime,
  oneLine,
  pruneSeen,
  RECONNECT_MAX_ATTEMPTS,
  recordMessage,
  rollDay,
  scrubIdentifiers,
  textLength,
  toGroupRecord,
} from './lib.js';

// אחרי כמה ניסיונות חיבור רצופים בלי הצלחה נשלחת התראה "עדיין מנותק".
// ניתוק בודד שחוזר תוך שניות (428 ברשת, 515 שמגיע תמיד אחרי סריקת QR) לא
// מתריע — התראה על כל הבהוב מלמדת להתעלם מהתראות. מה שמתריע הוא חיבור
// שלא חוזר: כאן, ובסוף ב-gave_up.
export const RECONNECT_ALERT_AFTER_ATTEMPTS = 3;

// כמה זמן חיבור צריך להישאר פתוח כדי להיחשב יציב. רק אז מתאפסים מונה
// הניסיונות וההתראות. איפוס ב-'open' עצמו היה מבטל את ההשהיה הגדלה בדיוק
// במצב המסוכן: חיבור שנפתח ונופל מיד (שגיאת stream אחרי הכניסה) היה חוזר
// כל 3 שניות לנצח, בלי התראה ובלי עצירה — וגם שולח "מחובר" ו"נפל" בכל סבב.
// זה לא איפוס לפי שעון במובן של הבאג ב-myAgent (שם נמדד הזמן מאז ready
// בזמן ההשהיות, בלי חיבור פתוח): כאן נמדד רק זמן רצוף שבו החיבור פתוח, וכל
// סגירה מבטלת את הטיימר.
export const STABLE_CONNECTION_MS = 60 * 1000;

function alertText(kind, code, detail, qrHint) {
  const c = Number.isFinite(code) ? ` (קוד ${code})` : '';
  const d = detail ? `\nפרטים: ${oneLine(detail, 500)}` : '';
  const qr = qrHint ? `\nלסריקה: ${qrHint}` : '';
  switch (kind) {
    case 'blocked':
      return `⛔ וואטסאפ: החשבון נחסם${c}. המאזין עצר — לא מתחבר מחדש ולא מחק את הסשן.${d}`;
    case 'logged_out':
      return `🚪 וואטסאפ: הקישור בוטל${c}. הסשן נמחק, וצריך לסרוק QR חדש.${qr}${d}`;
    case 'replaced':
      return `⚠️ וואטסאפ: חיבור אחר השתלט על הסשן${c}. המאזין עצר כדי לא להיכנס למאבק חיבורים.${d}`;
    case 'stopped':
      return `⚠️ וואטסאפ: וואטסאפ דחה את המכשיר המקושר${c}. המאזין עצר.${d}`;
    case 'gave_up':
      return `❌ וואטסאפ: ${RECONNECT_MAX_ATTEMPTS} ניסיונות חיבור רצופים נכשלו. המאזין עצר עד הפעלה מחדש של השירות ב-Render.${d}`;
    case 'reconnecting':
      return `🔌 וואטסאפ: החיבור נפל ולא חזר אחרי ${RECONNECT_ALERT_AFTER_ATTEMPTS} ניסיונות. ממשיך לנסות.${d}`;
    case 'needs_pairing':
      return `📭 וואטסאפ: אין סשן מקושר — המאזין לא מחובר עד שיסרקו QR.${qr}`;
    case 'crash_loop':
      return `🔁 וואטסאפ: השירות עלה כמה פעמים ברבע השעה האחרונה — כנראה קורס בלולאה.${d}`;
    case 'state_unreadable':
      return `💾 וואטסאפ: קובץ המונים קיים אבל לא נקרא. המאזין סופר בזיכרון בלבד ולא כותב עליו, כדי לא לדרוס אותו.${d}`;
    default:
      return `⚠️ וואטסאפ: ${kind}${c}${d}`;
  }
}

export function createListener(deps) {
  const {
    groupIds,
    timeZone,
    qrHint = '',
    loadAuth,
    makeSocket,
    purgeAuth,
    toQrDataUrl,
    notifier,
    stats,
    persistStats,
    helpers,
    timers,
    now,
    log,
  } = deps;

  // ===== מצב הריצה =====
  //   starting       — לפני החיבור הראשון
  //   needs_pairing  — אין סשן מקושר; מחכים שמישהו יפתח את /qr עם הטוקן
  //   pairing        — חיבור פתוח שמציג QR
  //   connecting     — מתחבר עם סשן קיים
  //   open           — מחובר
  //   reconnect_wait — מחכה לניסיון החיבור הבא
  //   stopped        — עצר בכוונה (חסימה וכו'); אין חיבור אוטומטי עד הפעלה מחדש
  const runtime = {
    state: 'starting',
    stopKind: null,
    sock: null,
    // מונה דורות: אירועים מחיבור ישן (אחרי שנפתח חדש) מתעלמים מהם
    generation: 0,
    linked: false,
    qrDataUrl: null,
    lastQrAt: null,
    reconnectAttempts: 0,
    reconnectTimer: null,
    stableTimer: null,
    // מספר סידורי ל-QR: המרת QR לתמונה אסינכרונית, ותוצאה שמגיעה אחרי שה-QR
    // הוחלף או שהחיבור נסגר — נזרקת (ראו onConnectionUpdate)
    qrSeq: 0,
    shuttingDown: false,
    groupsListed: false,
  };

  // מטמון שמות קבוצות: מזהה ← שם. חסום, כי מספר הקבוצות של החשבון חסום.
  // מתמלא מ-groupFetchAllParticipating (שאילתה אחת לכל הקבוצות) ומתעדכן
  // מ-groups.update / groups.upsert, ש-Baileys משדרת בעצמה כשקבוצה משתנה
  // (lib/Socket/groups.js:23-66) — בלי שאילתה לכל הודעה.
  const groupNames = new Map();

  function setState(next, extra = '') {
    if (runtime.state !== next) {
      log.info(`🔁 מצב: ${runtime.state} ← ${next}${extra ? ` (${extra})` : ''}`);
    }
    runtime.state = next;
  }

  // ===== התראות =====
  // כל סוג נשלח פעם אחת לכל תקופת ניתוק; המונה מתאפס כשהחיבור נפתח, ואז
  // נשלחת גם הודעת "מחובר" — כדי שאחרי התראה יהיה ברור אם זה נפתר.
  const alertedKinds = new Set();

  async function alert(kind, code = null, detail = '') {
    if (alertedKinds.has(kind)) return false;
    alertedKinds.add(kind);
    const withQr = kind === 'logged_out' || kind === 'needs_pairing';
    return notifier.send(alertText(kind, code, detail, withQr ? qrHint : ''));
  }

  // ===== חיבור =====
  function clearReconnectTimer() {
    if (runtime.reconnectTimer) {
      timers.clearTimeout(runtime.reconnectTimer);
      runtime.reconnectTimer = null;
    }
  }

  function clearStableTimer() {
    if (runtime.stableTimer) {
      timers.clearTimeout(runtime.stableTimer);
      runtime.stableTimer = null;
    }
  }

  // החיבור נשאר פתוח STABLE_CONNECTION_MS — עכשיו הוא נחשב יציב.
  function onStable() {
    runtime.stableTimer = null;
    if (runtime.state !== 'open') return;
    runtime.reconnectAttempts = 0;
    const hadAlerts = alertedKinds.size > 0;
    alertedKinds.clear();
    log.info('✅ החיבור יציב — מונה הניסיונות וההתראות אופסו.');
    if (hadAlerts) void notifier.send('✅ וואטסאפ: המאזין מחובר.');
  }

  // מתזמן החיבור היחיד. אין מסלול שמתחבר מחדש בלי לעבור כאן: ההשהיה גדלה,
  // והמונה מתאפס רק כשהחיבור נפתח בפועל — לא לפי שעון (הלקח של myAgent:
  // ההשהיות עצמן מקדמות את השעון ויוצרות אשליה של "חיבור יציב").
  function scheduleReconnect(reason) {
    if (runtime.shuttingDown || runtime.state === 'stopped') return;
    if (runtime.reconnectTimer) return; // כבר מתוזמן — לא מכפילים
    runtime.reconnectAttempts += 1;
    if (runtime.reconnectAttempts > RECONNECT_MAX_ATTEMPTS) {
      runtime.stopKind = 'gave_up';
      setState('stopped', 'gave_up');
      log.error(`❌ ${RECONNECT_MAX_ATTEMPTS} ניסיונות חיבור רצופים נכשלו — עוצר ומתריע.`);
      void alert('gave_up', null, `סיבה אחרונה: ${reason}`);
      return;
    }
    // מתזמנים עכשיו את ניסיון N+1, כלומר N ניסיונות כבר נכשלו
    if (runtime.reconnectAttempts > RECONNECT_ALERT_AFTER_ATTEMPTS) {
      void alert('reconnecting', null, `סיבה אחרונה: ${reason}`);
    }
    const delay = backoffDelayMs(runtime.reconnectAttempts);
    setState('reconnect_wait');
    log.info(
      `🔄 חיבור מחדש ${runtime.reconnectAttempts}/${RECONNECT_MAX_ATTEMPTS} בעוד ${Math.round(delay / 1000)}s (סיבה: ${reason})`,
    );
    runtime.reconnectTimer = timers.setTimeout(() => {
      runtime.reconnectTimer = null;
      startSocket('reconnect').catch((err) => {
        logError('❌ פתיחת חיבור נכשלה:', err);
        scheduleReconnect('start failed');
      });
    }, delay);
  }

  // פתיחות מקבילות מתאחדות לאחת: שני רענונים של /qr בהפרש של אלפיות שנייה
  // היו פותחים שני חיבורים, כי המצב משתנה רק אחרי ה-await הראשון (myAgent).
  let startInFlight = null;
  function startSocket(trigger) {
    if (!startInFlight) {
      startInFlight = openSocket(trigger).finally(() => {
        startInFlight = null;
      });
    }
    return startInFlight;
  }

  // בלי סשן מקושר — פותח רק כשהתבקש QR (trigger === 'pairing'), כדי שלא
  // ייווצרו QR-ים וחיבורים כשאף אחד לא סורק.
  async function openSocket(trigger) {
    clearReconnectTimer();
    if (runtime.shuttingDown || runtime.state === 'stopped') return;
    const gen = ++runtime.generation;

    const auth = await loadAuth();
    // בזמן ה-await אפשר היה להתחיל כיבוי או לעצור. בלי הבדיקה החוזרת נפתח
    // חיבור חדש אחרי ש-shutdown() כבר חזרה.
    if (runtime.shuttingDown || runtime.state === 'stopped') return;
    // creds.me ולא creds.registered — ראו classifyDisconnect ב-lib.js
    const linked = Boolean(auth.state.creds.me?.id);
    runtime.linked = linked;
    if (!linked && trigger !== 'pairing') {
      setState('needs_pairing');
      log.info('📭 אין סשן מקושר — מחכה לפתיחת /qr עם הטוקן.');
      void alert('needs_pairing');
      return;
    }

    // קודם החיבור והמאזינים, ורק אחר כך המצב (K15: הסימון לא מתפרסם לפני
    // הערך שהוא מסמן). אם 'pairing' היה נקבע לפני makeSocket והיצירה נכשלה,
    // המצב היה נתקע ב-pairing ו-/qr לא היה מנסה שוב לעולם. כשל כאן משאיר את
    // המצב הקודם (needs_pairing / reconnect_wait), וחיבור שכבר נוצר נסגר.
    const raw = makeSocket(auth);
    let sock;
    try {
      sock = guardSocket(raw);
      sock.ev.on('creds.update', () => {
        auth.saveCreds().catch((err) => logError('❌ שמירת פרטי הסשן נכשלה:', err));
      });
      sock.ev.on('connection.update', (update) => {
        if (gen !== runtime.generation) return;
        onConnectionUpdate(sock, auth, update).catch((err) => logError('שגיאה בטיפול בעדכון חיבור:', err));
      });
      sock.ev.on('messages.upsert', (event) => {
        if (gen !== runtime.generation) return;
        onMessagesUpsert(event);
      });
      sock.ev.on('groups.update', (updates) => rememberGroupNames(updates));
      sock.ev.on('groups.upsert', (groups) => rememberGroupNames(groups));
    } catch (err) {
      try {
        Promise.resolve(raw && raw.end && raw.end(undefined)).catch(() => {
          // החיבור לא הוקם עד הסוף — סגירה שנכשלת כאן אין לה מה לדווח מעבר לשגיאה המקורית
        });
      } catch {
        // כנ"ל: השגיאה המקורית היא זו שנזרקת ונרשמת אצל הקורא
      }
      throw err;
    }
    runtime.sock = sock;
    setState(linked ? 'connecting' : 'pairing', trigger);
  }

  async function onConnectionUpdate(sock, auth, update) {
    const { connection, lastDisconnect, qr } = update || {};

    if (qr) {
      const seq = ++runtime.qrSeq;
      try {
        const dataUrl = await toQrDataUrl(qr);
        // בזמן ההמרה ה-QR יכול היה להתחלף, או שהחיבור נסגר (QR פג, סריקה,
        // ניתוק). תמונה ישנה שמתפרסמת אחרי זה הייתה מוצגת ב-/qr לנצח —
        // והדף לא היה מבקש חיבור חדש, כי "יש QR".
        if (seq !== runtime.qrSeq || runtime.sock !== sock) return;
        runtime.qrDataUrl = dataUrl;
        runtime.lastQrAt = new Date(now()).toISOString();
        log.info('📱 QR חדש מוכן בדף /qr');
      } catch (err) {
        logError('כשל ביצירת תמונת QR:', err);
      }
    }

    if (connection === 'open') {
      runtime.qrSeq += 1;
      runtime.qrDataUrl = null;
      runtime.linked = true;
      runtime.stopKind = null;
      setState('open');
      log.info('✅ מאזין הוואטסאפ מחובר.');
      // המונה וההתראות מתאפסים רק אם החיבור נשאר פתוח — ראו STABLE_CONNECTION_MS
      clearStableTimer();
      runtime.stableTimer = timers.setTimeout(onStable, STABLE_CONNECTION_MS);
      void listGroupsOnce(sock);
      return;
    }

    if (connection !== 'close') return;

    clearStableTimer();
    runtime.sock = null;
    runtime.qrSeq += 1;
    runtime.qrDataUrl = null;
    if (runtime.shuttingDown) return;

    const err = lastDisconnect && lastDisconnect.error;
    const statusCode = err && err.output ? err.output.statusCode : undefined;
    // טקסט מהשרת ומהספרייה — בלי מזהים לפני שהוא מגיע ללוג או לטלגרם (K7)
    const message = scrubIdentifiers((err && err.message) || '');
    const data = err && err.data ? scrubIdentifiers(safeJson(err.data)) : '';
    // creds.me מתעדכן בזיכרון ברגע הקישור (Object.assign ב-lib/Socket/socket.js:855),
    // ולכן נבדק כאן ולא נלקח מתחילת החיבור.
    const linked = Boolean(auth.state.creds.me?.id);
    runtime.linked = linked;
    log.warn(
      `🔌 החיבור נסגר: code=${statusCode} reason="${oneLine(message, 200)}"${data ? ` data=${oneLine(data, 300)}` : ''} linked=${linked}`,
    );

    // ההחלטה לפי ההודעה המקורית (QR_EXPIRED_MESSAGE), לא לפי הגרסה המנוקה
    const decision = classifyDisconnect({ statusCode, message: (err && err.message) || '', linked });
    const detail = [message, data].filter(Boolean).join(' | ');
    switch (decision.action) {
      case 'stop':
        runtime.stopKind = decision.kind;
        setState('stopped', decision.kind);
        log.error(`⛔ עוצר (${decision.kind}). אין חיבור אוטומטי עד הפעלה מחדש של השירות.`);
        await alert(decision.kind, statusCode, detail);
        return;
      case 'relink':
        purgeAuth();
        runtime.linked = false;
        setState('needs_pairing', 'logged_out');
        await alert('logged_out', statusCode, detail);
        return;
      case 'pairing_expired':
        setState('needs_pairing', 'qr expired');
        log.info('⌛ ה-QR פג בלי סריקה. פתיחה חוזרת של /qr תיצור חדש.');
        return;
      default:
        scheduleReconnect(`code ${statusCode}`);
    }
  }

  // ===== קבוצות =====
  function rememberGroupNames(list) {
    for (const g of Array.isArray(list) ? list : []) {
      if (g && typeof g.id === 'string' && typeof g.subject === 'string') groupNames.set(g.id, g.subject);
    }
  }

  function groupLabel(id) {
    const name = groupNames.get(id);
    return name ? `${oneLine(name, 60)} (${id})` : id;
  }

  // בעלייה: כל הקבוצות שהחשבון חבר בהן, עם המזהה והשם, כדי לבחור מתוכן את
  // WA_GROUP_IDS. פעם אחת לתהליך — אחרי זה groups.update מעדכן את המטמון.
  // אם השאילתה נכשלה, היא תנוסה שוב בפתיחת החיבור הבאה.
  async function listGroupsOnce(sock) {
    if (runtime.groupsListed) return;
    let all;
    try {
      all = await sock.groupFetchAllParticipating();
    } catch (err) {
      logError('⚠️ טעינת רשימת הקבוצות נכשלה (תנוסה שוב בחיבור הבא):', err);
      return;
    }
    runtime.groupsListed = true;
    const groups = Object.values(all || {});
    rememberGroupNames(groups);
    log.info(`👥 החשבון חבר ב-${groups.length} קבוצות (✅ = במעקב לפי WA_GROUP_IDS):`);
    for (const g of groups.sort((a, b) => String(a.subject).localeCompare(String(b.subject)))) {
      const mark = groupIds.has(g.id) ? '✅' : '⬜';
      const size = Number.isFinite(g.size) ? ` | ${g.size} משתתפים` : '';
      log.info(`👥 ${mark} ${g.id} | ${oneLine(g.subject || '(בלי שם)', 80)}${size}`);
    }
    for (const id of groupIds) {
      if (!all || !all[id]) log.warn(`⚠️ הקבוצה ${id} ב-WA_GROUP_IDS, אבל החשבון לא חבר בה.`);
    }
  }

  // ===== קבלת הודעות =====
  // notify (הודעה חיה) וגם append (הצטברה בזמן ניתוק,
  // lib/Socket/messages-recv.js:1432): ליד שנכתב בזמן restart הוא עדיין ליד.
  function onMessagesUpsert(event) {
    const { messages, type } = event || {};
    for (const msg of Array.isArray(messages) ? messages : []) {
      try {
        handleMessage(msg, type);
      } catch (err) {
        logError('שגיאה בטיפול בהודעה:', err);
      }
    }
  }

  // סינכרונית מתחילה ועד סוף — אין await בין בדיקת הכפילות לבין הספירה.
  // הסדר חשוב: קודם בודקים שזו הודעת תוכן מקבוצה במעקב, ורק אז תופסים את
  // המזהה. הודעה שהגיעה ריקה (stub, לפני פענוח) לא תופסת אותו, כדי שהגרסה
  // המפוענחת, שמגיעה אחר כך עם אותו key.id, תיספר
  // (lib/Socket/messages-recv.js:1340-1358, lib/Utils/process-message.js:352).
  // פרטיות ומקבוצות שלא ברשימה — מתעלמים בשקט, בלי שורת לוג. לא דרך
  // shouldIgnoreJid: עליה הספרייה עונה לשרת ב-NACK חריג (Ck, סעיף 11.6).
  function handleMessage(msg, upsertType) {
    const record = toGroupRecord(msg, upsertType, helpers);
    if (!record || !groupIds.has(record.groupId)) return;

    // מעבר יום קודם לספירה: הודעה שמגיעה אחרי חצות ולפני פעימת הטיימר
    // הבאה (עד דקה) הייתה נספרת ליום שנגמר.
    dailyTick();
    const nowMs = now();
    if (!claimMessage(stats, dedupKey(record), nowMs)) {
      log.info(`♻️ כפילות נתפסה ולא נספרה: ${groupLabel(record.groupId)} | ${upsertType}`);
      return;
    }
    const length = textLength(record.text);
    recordMessage(stats, record.groupId, length > 0);
    persistStats();
    const sent = record.timestampSec ? localTime(record.timestampSec * 1000, timeZone) : '?';
    log.info(
      `💬 ${groupLabel(record.groupId)} | נשלחה ${sent} | ${length} תווים | ${record.type} | ${record.offline ? 'מהשבתה' : 'חי'}`,
    );
  }

  // ===== סיכום יומי =====
  // נקרא מטיימר בכל דקה. כשהתאריך המקומי מתחלף — שורת סיכום על היום שנגמר.
  function dailyTick({ late = false } = {}) {
    const nowMs = now();
    const summary = rollDay(stats, localDayKey(nowMs, timeZone));
    if (!summary) return null;
    pruneSeen(stats, nowMs);
    persistStats();
    const line = formatDailySummary(summary, groupIds, (id) => groupNames.get(id), { late });
    log.info(line);
    return line;
  }

  // ===== כיבוי =====
  function shutdown() {
    if (runtime.shuttingDown) return;
    runtime.shuttingDown = true;
    clearReconnectTimer();
    clearStableTimer();
    if (runtime.sock) {
      try {
        Promise.resolve(runtime.sock.end(undefined)).catch((err) => logError('סגירת החיבור נכשלה:', err));
      } catch (err) {
        logError('סגירת החיבור נכשלה:', err);
      }
    }
  }

  // עזר ללוג שגיאות מפורט: שם החריגה תמיד (באג #20 — חריגה עם message ריק
  // הופיעה בלוג כהודעה חסרת פשר), ו-message לבד יכול להיות ריק.
  function logError(prefix, err) {
    const parts = [prefix];
    if (err) {
      parts.push(`type=${err.name || err.constructor?.name || typeof err}`);
      if (err.message) parts.push(`message="${scrubIdentifiers(oneLine(err.message, 300))}"`);
      if (err.code) parts.push(`code=${scrubIdentifiers(String(err.code))}`);
      if (err.output && err.output.statusCode) parts.push(`status=${err.output.statusCode}`);
    }
    log.error(parts.join(' | '));
    if (err && err.stack) log.error(scrubIdentifiers(err.stack));
  }

  return {
    runtime,
    groupNames,
    startSocket,
    scheduleReconnect,
    alert,
    dailyTick,
    shutdown,
    logError,
    // לדף /qr: פותח חיבור לקישור רק כשבאמת ממתינים לקישור
    requestPairing() {
      if (runtime.state !== 'needs_pairing') return;
      startSocket('pairing').catch((err) => logError('❌ פתיחת חיבור לקישור נכשלה:', err));
    },
  };
}

export function safeJson(value) {
  try {
    const s = JSON.stringify(value, (_k, v) => (typeof v === 'bigint' ? String(v) : v));
    return s === undefined ? String(value) : s.slice(0, 500);
  } catch {
    return String(value);
  }
}
