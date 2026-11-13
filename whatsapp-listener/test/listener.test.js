// בדיקות התנהגות של המאזין, דרך אותו ממשק ש-Baileys משתמשת בו: אירועים על
// sock.ev (connection.update, messages.upsert, groups.update). החיבור, הדיסק,
// הטיימרים וטלגרם מוחלפים בדמויות שרושמות כל קריאה, כדי לבדוק מה **קרה**:
// האם הסשן נמחק, האם תוזמן חיבור חוזר, האם נשלחה התראה, מה נכתב ללוג.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { getContentType, normalizeMessageContent, toNumber } from '@whiskeysockets/baileys';
import { emptyStats, localDayKey } from '../lib.js';
import { createListener, RECONNECT_ALERT_AFTER_ATTEMPTS, STABLE_CONNECTION_MS } from '../listener.js';

const LISTED = '120363402840406015@g.us';
const OTHER_GROUP = '120363999999999999@g.us';
const TZ = 'Asia/Jerusalem';

function makeEmitter() {
  const handlers = new Map();
  return {
    on(name, fn) {
      if (!handlers.has(name)) handlers.set(name, []);
      handlers.get(name).push(fn);
    },
    emit(name, payload) {
      for (const fn of handlers.get(name) || []) fn(payload);
    },
  };
}

// דמות של החיבור: ev אמיתי (פולט אירועים), ופונקציות שרושמות קריאות. כוללת
// גם פונקציות אסורות — אם הקוד ינסה לקרוא להן, השומר יזרוק והמונה יראה.
function makeFakeSocket(groups = {}) {
  const sock = {
    ev: makeEmitter(),
    endCalls: 0,
    forbiddenCalls: 0,
    groupFetchCalls: 0,
    async groupFetchAllParticipating() {
      sock.groupFetchCalls += 1;
      return groups;
    },
    async end() {
      sock.endCalls += 1;
    },
    sendMessage() {
      sock.forbiddenCalls += 1;
    },
    readMessages() {
      sock.forbiddenCalls += 1;
    },
  };
  return sock;
}

function makeHarness({ linked = true, groupIds = [LISTED], groups, loadAuth, makeSocket, toQrDataUrl } = {}) {
  const h = {
    logs: [],
    alerts: [],
    sockets: [],
    purgeCalls: 0,
    persistCalls: 0,
    timers: [],
    nowMs: Date.UTC(2026, 10, 13, 10, 0),
    creds: { me: linked ? { id: '972500000000:1@s.whatsapp.net' } : undefined },
  };
  const log = {
    info: (m) => h.logs.push(['info', String(m)]),
    warn: (m) => h.logs.push(['warn', String(m)]),
    error: (m) => h.logs.push(['error', String(m)]),
  };
  h.stats = emptyStats(localDayKey(h.nowMs, TZ));
  h.listener = createListener({
    groupIds: new Set(groupIds),
    timeZone: TZ,
    qrHint: 'https://example.invalid/qr?token=<QR_ACCESS_TOKEN>',
    loadAuth: loadAuth || (async () => ({ state: { creds: h.creds, keys: {} }, saveCreds: async () => {} })),
    makeSocket: (auth) => {
      if (makeSocket) makeSocket(auth); // דמות שיכולה לזרוק לפני שנוצר חיבור
      const s = makeFakeSocket(groups);
      h.sockets.push(s);
      return s;
    },
    purgeAuth: () => {
      h.purgeCalls += 1;
    },
    toQrDataUrl: toQrDataUrl || (async (qr) => `data:image/png;base64,${qr}`),
    notifier: {
      send: async (text) => {
        h.alerts.push(text);
        return true;
      },
    },
    stats: h.stats,
    persistStats: () => {
      h.persistCalls += 1;
    },
    helpers: { normalizeMessageContent, getContentType, toNumber },
    timers: {
      setTimeout: (fn, ms) => {
        const t = { fn, ms, cleared: false };
        h.timers.push(t);
        return t;
      },
      clearTimeout: (t) => {
        if (t) t.cleared = true;
      },
    },
    now: () => h.nowMs,
    log,
  });
  h.sock = () => h.sockets[h.sockets.length - 1];
  h.emit = (name, payload) => h.sock().ev.emit(name, payload);
  h.close = (statusCode, message = '') =>
    h.emit('connection.update', {
      connection: 'close',
      lastDisconnect: { error: Object.assign(new Error(message), { output: { statusCode } }) },
    });
  // שני סוגי טיימרים: חיבור חוזר (השהיה גדלה) וטיימר היציבות. מופרדים כדי
  // שבדיקה תחליט במפורש אם החיבור "נשאר פתוח" או נפל לפני כן.
  h.pendingTimers = () => h.timers.filter((t) => !t.cleared && !t.fired && t.ms !== STABLE_CONNECTION_MS);
  h.pendingStable = () => h.timers.filter((t) => !t.cleared && !t.fired && t.ms === STABLE_CONNECTION_MS);
  const fire = async (list) => {
    for (const t of list) {
      t.fired = true;
      t.fn();
    }
    await flush();
  };
  h.runTimers = () => fire(h.pendingTimers());
  h.runStable = () => fire(h.pendingStable());
  h.messageLogs = () => h.logs.filter(([, m]) => m.startsWith('💬'));
  return h;
}

// מחכה שה-promises הפנימיים (await בתוך handlers) יסתיימו
const flush = () => new Promise((r) => setImmediate(r));

// חיבור שנפתח ונשאר פתוח מספיק זמן כדי להיחשב יציב
async function connected(opts) {
  const h = makeHarness(opts);
  await h.listener.startSocket('startup');
  h.emit('connection.update', { connection: 'open' });
  await flush();
  await h.runStable();
  return h;
}

function groupMsg({ group = LISTED, id = 'MSG1', text = 'מחפש מפתח לאוטומציה בוואטסאפ', message } = {}) {
  return {
    key: { remoteJid: group, id, fromMe: false, participant: '155516504436974@lid' },
    pushName: 'דנה',
    messageTimestamp: Math.floor(Date.UTC(2026, 10, 13, 9, 58) / 1000),
    message: message === undefined ? { conversation: text } : message,
  };
}

// ===== הודעות: מה נרשם ומה לא =====

test('הודעה פרטית — לא נרשמת ולא נספרת', async () => {
  const h = await connected();
  for (const jid of ['972541234567@s.whatsapp.net', '155516504436974@lid']) {
    const msg = groupMsg({ id: `P-${jid}` });
    msg.key = { remoteJid: jid, id: `P-${jid}`, fromMe: false };
    h.emit('messages.upsert', { messages: [msg], type: 'notify' });
  }
  assert.equal(h.messageLogs().length, 0);
  assert.deepEqual(h.stats.daily, {});
  assert.equal(h.stats.seen.size, 0);
});

test('הודעה מקבוצה שלא ברשימה — לא נרשמת ולא נספרת', async () => {
  const h = await connected();
  h.emit('messages.upsert', { messages: [groupMsg({ group: OTHER_GROUP })], type: 'notify' });
  assert.equal(h.messageLogs().length, 0);
  assert.deepEqual(h.stats.daily, {});
});

test('רשימה ריקה — אף קבוצה לא נרשמת', async () => {
  const h = await connected({ groupIds: [] });
  h.emit('messages.upsert', { messages: [groupMsg()], type: 'notify' });
  assert.equal(h.messageLogs().length, 0);
});

test('הודעה מקבוצה ברשימה — שורת לוג עם קבוצה, שעה ואורך, בלי התוכן ובלי השולח', async () => {
  const h = await connected({ groups: { [LISTED]: { id: LISTED, subject: 'פיתוח AI', size: 120 } } });
  const text = 'מחפש מפתח לאוטומציה בוואטסאפ';
  h.emit('messages.upsert', { messages: [groupMsg({ text })], type: 'notify' });
  const lines = h.messageLogs();
  assert.equal(lines.length, 1);
  const line = lines[0][1];
  assert.match(line, /פיתוח AI \(120363402840406015@g\.us\)/);
  assert.match(line, /נשלחה 11:58/); // 09:58Z = 11:58 בירושלים בנובמבר
  assert.match(line, new RegExp(`${Array.from(text).length} תווים`));
  assert.match(line, /\| חי$/);
  for (const secret of [text, 'דנה', '155516504436974']) assert.ok(!line.includes(secret), `leaked: ${secret}`);
  assert.deepEqual(h.stats.daily[LISTED], { count: 1, withText: 1 });
  assert.ok(h.persistCalls >= 1);
});

test('אותה הודעה ב-notify וב-append נרשמת ונספרת פעם אחת', async () => {
  const h = await connected();
  h.emit('messages.upsert', { messages: [groupMsg({ id: 'DUP' })], type: 'notify' });
  h.emit('messages.upsert', { messages: [groupMsg({ id: 'DUP' })], type: 'append' });
  assert.equal(h.messageLogs().length, 1);
  assert.deepEqual(h.stats.daily[LISTED], { count: 1, withText: 1 });
  assert.equal(h.logs.filter(([, m]) => m.startsWith('♻️')).length, 1);
});

test('אותה הודעה בשני אירועים במקביל — נספרת פעם אחת', async () => {
  const h = await connected();
  await Promise.all(
    ['notify', 'append', 'notify'].map((type) =>
      Promise.resolve().then(() => h.emit('messages.upsert', { messages: [groupMsg({ id: 'PAR' })], type })),
    ),
  );
  assert.equal(h.messageLogs().length, 1);
  assert.equal(h.stats.daily[LISTED].count, 1);
});

test('stub בלי תוכן לא תופס את המזהה — הגרסה המפוענחת עם אותו key.id נספרת', async () => {
  const h = await connected();
  h.emit('messages.upsert', { messages: [groupMsg({ id: 'STUB', message: null })], type: 'notify' });
  assert.equal(h.messageLogs().length, 0);
  h.emit('messages.upsert', { messages: [groupMsg({ id: 'STUB', text: 'פוענח' })], type: 'notify' });
  assert.equal(h.messageLogs().length, 1);
  assert.equal(h.stats.daily[LISTED].count, 1);
});

test('הודעה שלי (fromMe) ותגובת אימוג׳י — לא נספרות', async () => {
  const h = await connected();
  const mine = groupMsg({ id: 'MINE' });
  mine.key.fromMe = true;
  h.emit('messages.upsert', {
    messages: [mine, groupMsg({ id: 'R', message: { reactionMessage: { text: '👍' } } })],
    type: 'notify',
  });
  assert.equal(h.messageLogs().length, 0);
});

test('הודעה פגומה באמצע באצ׳ לא מפילה את השאר', async () => {
  const h = await connected();
  h.emit('messages.upsert', { messages: [null, { key: { remoteJid: LISTED } }, groupMsg({ id: 'OK' })], type: 'notify' });
  assert.equal(h.messageLogs().length, 1);
});

// ===== סגירת חיבור =====

test('403: לא מוחק סשן, לא מתחבר מחדש, עוצר ושולח התראת חסימה', async () => {
  const h = await connected();
  h.close(403, 'Connection Failure');
  await flush();
  assert.equal(h.purgeCalls, 0, 'הסשן נמחק אחרי חסימה');
  assert.equal(h.pendingTimers().length, 0, 'תוזמן חיבור חוזר אחרי חסימה');
  assert.equal(h.listener.runtime.state, 'stopped');
  assert.equal(h.listener.runtime.stopKind, 'blocked');
  assert.equal(h.alerts.length, 1);
  assert.match(h.alerts[0], /נחסם \(קוד 403\)/);
  // גם ניסיון מפורש לפתוח חיבור, או בקשת QR, לא פותחים אחרי עצירה
  await h.listener.startSocket('reconnect');
  h.listener.requestPairing();
  await flush();
  assert.equal(h.sockets.length, 1);
});

for (const code of [401, 419]) {
  test(`${code}: מוחק סשן, מתריע, וממתין ל-QR בלי להתחבר מחדש`, async () => {
    const h = await connected();
    h.close(code);
    await flush();
    assert.equal(h.purgeCalls, 1);
    assert.equal(h.pendingTimers().length, 0, 'תוזמן חיבור חוזר אחרי ביטול קישור');
    assert.equal(h.listener.runtime.state, 'needs_pairing');
    assert.equal(h.listener.runtime.linked, false);
    assert.equal(h.alerts.length, 1);
    assert.match(h.alerts[0], new RegExp(`הקישור בוטל \\(קוד ${code}\\)`));
    assert.match(h.alerts[0], /QR/);
    assert.ok(!h.alerts[0].includes('token=') || h.alerts[0].includes('<QR_ACCESS_TOKEN>'));
    assert.equal(h.sockets.length, 1);
  });
}

test('440: עוצר ומתריע, בלי מחיקה ובלי חיבור חוזר', async () => {
  const h = await connected();
  h.close(440, 'Stream Errored (conflict)');
  await flush();
  assert.equal(h.purgeCalls, 0);
  assert.equal(h.pendingTimers().length, 0);
  assert.equal(h.listener.runtime.stopKind, 'replaced');
  assert.equal(h.alerts.length, 1);
});

test('ניתוק חולף (428): חיבור חוזר אחרי 3 שניות, בלי מחיקה ובלי התראה; לוג עם הקוד והסיבה', async () => {
  const h = await connected();
  h.close(428, 'Connection Terminated');
  await flush();
  assert.equal(h.purgeCalls, 0);
  assert.equal(h.alerts.length, 0);
  assert.deepEqual(
    h.pendingTimers().map((t) => t.ms),
    [3000],
  );
  assert.ok(h.logs.some(([lvl, m]) => lvl === 'warn' && m.includes('code=428') && m.includes('Connection Terminated')));
  await h.runTimers();
  assert.equal(h.sockets.length, 2);
});

test('השהיה גדלה, התראה כשהחיבור לא חוזר, ועצירה אחרי 8 ניסיונות', async () => {
  const h = await connected();
  const delays = [];
  for (let i = 0; i < 9; i++) {
    h.close(500, 'Stream Errored (unknown)');
    await flush();
    const pending = h.pendingTimers();
    if (pending.length === 0) break;
    delays.push(pending[0].ms);
    if (i + 1 === RECONNECT_ALERT_AFTER_ATTEMPTS) assert.equal(h.alerts.length, 0, 'התראה מוקדמת מדי');
    await h.runTimers();
  }
  assert.deepEqual(delays, [3000, 6000, 12000, 24000, 48000, 96000, 192000, 300000]);
  assert.equal(h.listener.runtime.state, 'stopped');
  assert.equal(h.listener.runtime.stopKind, 'gave_up');
  assert.equal(h.purgeCalls, 0);
  assert.equal(h.alerts.filter((a) => a.includes('ממשיך לנסות')).length, 1);
  assert.equal(h.alerts.filter((a) => a.includes('8 ניסיונות')).length, 1);
});

test('חיבור שנשאר פתוח אחרי התראה שולח "מחובר" ומאפס את המונה; בלי התראה קודמת — שקט', async () => {
  const h = await connected();
  assert.equal(h.alerts.length, 0);
  for (let i = 0; i < RECONNECT_ALERT_AFTER_ATTEMPTS + 1; i++) {
    h.close(500);
    await flush();
    await h.runTimers();
  }
  assert.equal(h.alerts.length, 1);
  h.emit('connection.update', { connection: 'open' });
  await flush();
  // נפתח — אבל עוד לא יציב: אין "מחובר" והמונה לא התאפס
  assert.equal(h.alerts.length, 1);
  assert.ok(h.listener.runtime.reconnectAttempts > 0);
  await h.runStable();
  assert.equal(h.alerts.length, 2);
  assert.match(h.alerts[1], /מחובר/);
  assert.equal(h.listener.runtime.reconnectAttempts, 0);
  // ניתוק בודד אחרי זה — אין התראה
  h.close(428);
  await flush();
  assert.equal(h.alerts.length, 2);
});

test('חיבור שנפתח ונופל מיד: ההשהיה ממשיכה לגדול, התראה אחת, ועצירה אחרי 8 — בלי הצפת "מחובר"', async () => {
  const h = await connected();
  const delays = [];
  for (let i = 0; i < 12; i++) {
    h.close(500, 'Stream Errored (unknown)');
    await flush();
    const pending = h.pendingTimers();
    if (pending.length === 0) break;
    delays.push(pending[0].ms);
    await h.runTimers();
    // החיבור נפתח שוב — ונופל לפני שהוא נחשב יציב
    h.emit('connection.update', { connection: 'open' });
    await flush();
  }
  assert.deepEqual(delays, [3000, 6000, 12000, 24000, 48000, 96000, 192000, 300000]);
  assert.equal(h.listener.runtime.state, 'stopped');
  assert.equal(h.listener.runtime.stopKind, 'gave_up');
  assert.equal(h.alerts.filter((a) => a.includes('ממשיך לנסות')).length, 1);
  assert.equal(h.alerts.filter((a) => a.includes('מחובר')).length, 0);
});

test('515 אחרי סריקה: חיבור חוזר דרך המתזמן, בלי התראה', async () => {
  const h = await connected();
  h.close(515, 'Stream Errored (restart required)');
  await flush();
  assert.equal(h.alerts.length, 0);
  assert.deepEqual(
    h.pendingTimers().map((t) => t.ms),
    [3000],
  );
});

test('אירועים מחיבור ישן (אחרי שנפתח חדש) לא משפיעים', async () => {
  const h = await connected();
  const old = h.sock();
  h.close(428);
  await flush();
  await h.runTimers();
  assert.equal(h.sockets.length, 2);
  old.ev.emit('connection.update', {
    connection: 'close',
    lastDisconnect: { error: Object.assign(new Error('x'), { output: { statusCode: 403 } }) },
  });
  old.ev.emit('messages.upsert', { messages: [groupMsg({ id: 'OLD' })], type: 'notify' });
  await flush();
  assert.notEqual(h.listener.runtime.state, 'stopped');
  assert.equal(h.messageLogs().length, 0);
});

// ===== עלייה וקישור =====

test('עלייה בלי סשן: לא פותח חיבור, ממתין ל-QR ומתריע פעם אחת', async () => {
  const h = makeHarness({ linked: false });
  await h.listener.startSocket('startup');
  await flush();
  assert.equal(h.sockets.length, 0);
  assert.equal(h.listener.runtime.state, 'needs_pairing');
  assert.equal(h.alerts.length, 1);
  assert.match(h.alerts[0], /אין סשן מקושר/);
  // בקשת QR פותחת חיבור לקישור
  h.listener.requestPairing();
  await flush();
  assert.equal(h.sockets.length, 1);
  assert.equal(h.listener.runtime.state, 'pairing');
  h.emit('connection.update', { qr: 'QRDATA' });
  await flush();
  assert.equal(h.listener.runtime.qrDataUrl, 'data:image/png;base64,QRDATA');
  // QR שפג — חוזרים להמתנה, בלי חיבור חדש ובלי התראה
  h.close(408, 'QR refs attempts ended');
  await flush();
  assert.equal(h.listener.runtime.state, 'needs_pairing');
  assert.equal(h.pendingTimers().length, 0);
  assert.equal(h.alerts.length, 1);
});

test('פתיחות מקבילות של /qr מתאחדות לחיבור אחד', async () => {
  const h = makeHarness({ linked: false });
  await h.listener.startSocket('startup');
  for (let i = 0; i < 5; i++) h.listener.requestPairing();
  await flush();
  assert.equal(h.sockets.length, 1);
});

// ===== קבוצות =====

test('בחיבור: רשימת כל הקבוצות נכתבת פעם אחת, עם סימון מעקב ואזהרה על קבוצה חסרה', async () => {
  const missing = '120363000000000001@g.us';
  const h = await connected({
    groupIds: [LISTED, missing],
    groups: {
      [LISTED]: { id: LISTED, subject: 'פיתוח AI', size: 120 },
      [OTHER_GROUP]: { id: OTHER_GROUP, subject: 'שם\nעם שבירה', size: 30 },
    },
  });
  const lines = h.logs.map(([, m]) => m);
  assert.ok(lines.some((m) => m.includes('חבר ב-2 קבוצות')));
  assert.ok(lines.some((m) => m.startsWith('👥 ✅ 120363402840406015@g.us | פיתוח AI | 120 משתתפים')));
  assert.ok(lines.some((m) => m.startsWith('👥 ⬜ 120363999999999999@g.us | שם עם שבירה')));
  assert.ok(lines.some((m) => m.includes(missing) && m.includes('לא חבר')));
  // חיבור נוסף לא שולח שאילתה נוספת
  h.close(428);
  await flush();
  await h.runTimers();
  h.emit('connection.update', { connection: 'open' });
  await flush();
  assert.equal(h.sockets.reduce((n, s) => n + s.groupFetchCalls, 0), 1);
});

test('groups.update מעדכן את שם הקבוצה בשורת הלוג', async () => {
  const h = await connected();
  h.emit('groups.update', [{ id: LISTED, subject: 'שם חדש' }]);
  h.emit('messages.upsert', { messages: [groupMsg({ id: 'N' })], type: 'notify' });
  assert.match(h.messageLogs()[0][1], /שם חדש \(120363402840406015@g\.us\)/);
});

// ===== סיכום יומי =====

test('סיכום יומי: נכתב במעבר היום המקומי, היומי מתאפס והמצטבר נשמר', async () => {
  const h = await connected({ groups: { [LISTED]: { id: LISTED, subject: 'פיתוח AI' } } });
  h.emit('messages.upsert', { messages: [groupMsg({ id: 'A' }), groupMsg({ id: 'B', message: { imageMessage: {} } })], type: 'notify' });
  assert.equal(h.listener.dailyTick(), null); // עדיין אותו יום
  h.nowMs = Date.UTC(2026, 10, 13, 22, 1); // 00:01 בירושלים, 14.11
  const line = h.listener.dailyTick();
  assert.match(line, /סיכום יומי 2026-11-13: 2 הודעות, 1 עם טקסט/);
  assert.match(line, /פיתוח AI: 2 \(מצטבר 2\)/);
  assert.deepEqual(h.stats.daily, {});
  assert.deepEqual(h.stats.totals[LISTED], { count: 2, withText: 1 });
  assert.equal(h.listener.dailyTick(), null);
});

// ===== קריאה בלבד =====

test('הקוד לא נוגע בפונקציות אסורות של החיבור בשום מסלול שנבדק כאן', async () => {
  const h = await connected({ groups: { [LISTED]: { id: LISTED, subject: 'x' } } });
  h.emit('messages.upsert', { messages: [groupMsg()], type: 'notify' });
  h.close(428);
  await flush();
  await h.runTimers();
  h.listener.shutdown();
  assert.equal(h.sockets.reduce((n, s) => n + s.forbiddenCalls, 0), 0);
});

// ===== מקרי קצה מהסקירה =====

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

test('המרת QR שמסתיימת אחרי שהחיבור נסגר — לא מתפרסמת, ו-/qr יכול לבקש חיבור חדש', async () => {
  const pending = [];
  const h = makeHarness({
    linked: false,
    toQrDataUrl: (qr) => {
      const d = deferred();
      pending.push({ qr, d });
      return d.promise;
    },
  });
  await h.listener.startSocket('startup');
  h.listener.requestPairing();
  await flush();
  h.emit('connection.update', { qr: 'OLD' });
  h.close(408, 'QR refs attempts ended'); // ה-QR פג לפני שההמרה הסתיימה
  await flush();
  pending[0].d.resolve('data:image/png;base64,OLD');
  await flush();
  assert.equal(h.listener.runtime.qrDataUrl, null);
  assert.equal(h.listener.runtime.state, 'needs_pairing');
  h.listener.requestPairing();
  await flush();
  assert.equal(h.sockets.length, 2, '/qr לא פתח חיבור חדש');
});

test('שני QR ברצף: המרה איטית של הישן לא דורסת את החדש', async () => {
  const pending = [];
  const h = makeHarness({
    linked: false,
    toQrDataUrl: (qr) => {
      const d = deferred();
      pending.push({ qr, d });
      return d.promise;
    },
  });
  await h.listener.startSocket('startup');
  h.listener.requestPairing();
  await flush();
  h.emit('connection.update', { qr: 'Q1' });
  h.emit('connection.update', { qr: 'Q2' });
  pending[1].d.resolve('data:Q2');
  await flush();
  pending[0].d.resolve('data:Q1');
  await flush();
  assert.equal(h.listener.runtime.qrDataUrl, 'data:Q2');
});

test('כיבוי בזמן טעינת הסשן — לא נפתח חיבור אחרי ש-shutdown חזרה', async () => {
  const gate = deferred();
  const h = makeHarness({
    loadAuth: async () => {
      await gate.promise;
      return { state: { creds: { me: { id: '972500000000:1@s.whatsapp.net' } }, keys: {} }, saveCreds: async () => {} };
    },
  });
  const opening = h.listener.startSocket('startup');
  h.listener.shutdown();
  gate.resolve();
  await opening;
  await flush();
  assert.equal(h.sockets.length, 0);
});

test('כשל ביצירת החיבור לקישור — המצב נשאר needs_pairing, ובקשת /qr הבאה מנסה שוב', async () => {
  let failures = 1;
  const h = makeHarness({
    linked: false,
    makeSocket: () => {
      if (failures-- > 0) throw new Error('boom in makeWASocket');
    },
  });
  await h.listener.startSocket('startup');
  h.listener.requestPairing();
  await flush();
  assert.equal(h.sockets.length, 0);
  assert.equal(h.listener.runtime.state, 'needs_pairing');
  assert.ok(h.logs.some(([lvl, m]) => lvl === 'error' && m.includes('boom in makeWASocket')));
  h.listener.requestPairing();
  await flush();
  assert.equal(h.sockets.length, 1);
  assert.equal(h.listener.runtime.state, 'pairing');
});

test('הודעה אחרי חצות, לפני פעימת הטיימר — נספרת ליום החדש, והסיכום של אתמול לא כולל אותה', async () => {
  const h = await connected({ groups: { [LISTED]: { id: LISTED, subject: 'פיתוח AI' } } });
  h.emit('messages.upsert', { messages: [groupMsg({ id: 'Y1' })], type: 'notify' });
  h.nowMs = Date.UTC(2026, 10, 13, 22, 0, 30); // 00:00:30 בירושלים, 14.11 — הטיימר עוד לא רץ
  h.emit('messages.upsert', { messages: [groupMsg({ id: 'T1' })], type: 'notify' });
  const summary = h.logs.map(([, m]) => m).find((m) => m.startsWith('📊 סיכום יומי'));
  assert.match(summary, /סיכום יומי 2026-11-13: 1 הודעות/);
  assert.equal(h.stats.day, '2026-11-14');
  assert.deepEqual(h.stats.daily[LISTED], { count: 1, withText: 1 });
  assert.deepEqual(h.stats.totals[LISTED], { count: 2, withText: 2 });
});

test('הודעת ניתוק מהשרת עם מזהים — נכתבת ללוג ולטלגרם בלי המספר', async () => {
  const h = await connected();
  h.emit('connection.update', {
    connection: 'close',
    lastDisconnect: {
      error: Object.assign(new Error('Connection Failure for 972541234567@s.whatsapp.net'), {
        output: { statusCode: 403 },
        data: { reason: '403', jid: '155516504436974@lid' },
      }),
    },
  });
  await flush();
  const all = [...h.logs.map(([, m]) => m), ...h.alerts].join('\n');
  assert.ok(!all.includes('972541234567'), all);
  assert.ok(!all.includes('155516504436974'), all);
  assert.match(h.alerts[0], /<jid>/);
});
