// בדיקות ללוגיקה הטהורה (lib.js). כל בדיקה כאן נכשלת אם ההחלטה שהיא שומרת
// עליה משתנה — במיוחד ההחלטות שנוגעות לחשבון: מתי עוצרים, מתי מוחקים סשן,
// מתי מתחברים שוב, ומה נספר.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { getContentType, normalizeMessageContent, toNumber } from '@whiskeysockets/baileys';
import {
  backoffDelayMs,
  claimMessage,
  classifyDisconnect,
  dedupKey,
  emptyStats,
  ForbiddenSocketAccess,
  formatDailySummary,
  guardSocket,
  localDayKey,
  localTime,
  mapContent,
  normalizeStats,
  oneLine,
  parseGroupIds,
  phoneFromJids,
  pruneSeen,
  pruneStarts,
  QR_EXPIRED_MESSAGE,
  RECONNECT_MAX_DELAY_MS,
  recordMessage,
  rollDay,
  serializeStats,
  safeText,
  safeTokenEqual,
  scrubIdentifiers,
  SEEN_MAX,
  SEEN_TTL_MS,
  SOCKET_ALLOWED_PROPS,
  startupDelayMs,
  STARTUP_WINDOW_MS,
  textLength,
  toGroupRecord,
} from '../lib.js';

const helpers = { normalizeMessageContent, getContentType, toNumber };
const GROUP = '120363402840406015@g.us';

// ===== סגירת חיבור =====

test('classifyDisconnect: 403 עוצר כחסימה — לא קישור מחדש ולא חיבור חוזר', () => {
  assert.deepEqual(classifyDisconnect({ statusCode: 403, message: 'Connection Failure', linked: true }), {
    action: 'stop',
    kind: 'blocked',
  });
  assert.equal(classifyDisconnect({ statusCode: 403, linked: false }).action, 'stop');
});

test('classifyDisconnect: 401 ו-419 הם קישור מחדש', () => {
  for (const statusCode of [401, 419]) {
    assert.deepEqual(classifyDisconnect({ statusCode, linked: true }), { action: 'relink', kind: 'logged_out' });
  }
});

test('classifyDisconnect: 440 ו-411 עוצרים', () => {
  assert.deepEqual(classifyDisconnect({ statusCode: 440, linked: true }), { action: 'stop', kind: 'replaced' });
  assert.deepEqual(classifyDisconnect({ statusCode: 411, linked: true }), { action: 'stop', kind: 'stopped' });
});

test('classifyDisconnect: QR שפג לפני קישור חוזר להמתנה; אחרי קישור 408 הוא ניתוק רגיל', () => {
  assert.deepEqual(classifyDisconnect({ statusCode: 408, message: QR_EXPIRED_MESSAGE, linked: false }), {
    action: 'pairing_expired',
    kind: null,
  });
  assert.equal(classifyDisconnect({ statusCode: 408, message: QR_EXPIRED_MESSAGE, linked: true }).action, 'reconnect');
});

test('classifyDisconnect: ניתוקים חולפים ו-515 עוברים דרך מתזמן החיבור', () => {
  for (const statusCode of [408, 428, 500, 503, 515, undefined]) {
    assert.equal(classifyDisconnect({ statusCode, linked: true }).action, 'reconnect', `code ${statusCode}`);
  }
});

// ===== השהיות =====

test('backoffDelayMs: 3 שניות, מכפיל, נעצר בתקרה, ואין אפס', () => {
  assert.equal(backoffDelayMs(1), 3000);
  assert.equal(backoffDelayMs(2), 6000);
  assert.equal(backoffDelayMs(3), 12000);
  assert.equal(backoffDelayMs(8), RECONNECT_MAX_DELAY_MS);
  assert.equal(backoffDelayMs(50), RECONNECT_MAX_DELAY_MS);
  assert.ok(backoffDelayMs(0) >= 3000);
});

test('startupDelayMs / pruneStarts: עלייה ראשונה מיידית, תכופות מחכות, ערכים לא תקינים מסוננים', () => {
  const now = 10 * STARTUP_WINDOW_MS;
  assert.equal(startupDelayMs([], now), 0);
  assert.equal(startupDelayMs([now - 1000], now), 3000);
  assert.equal(startupDelayMs([now - 3000, now - 2000, now - 1000], now), 12000);
  assert.equal(startupDelayMs([now - STARTUP_WINDOW_MS - 1], now), 0);
  assert.deepEqual(pruneStarts(['x', null, NaN, now - 5], now), [now - 5]);
  assert.equal(pruneStarts(Array.from({ length: 50 }, (_, i) => now - i * 1000), now).length, 20);
  assert.deepEqual(pruneStarts(undefined, now), []);
});

// ===== קבוצות =====

test('parseGroupIds: פסיקים/רווחים, השלמת @g.us, וערכים לא תקינים בנפרד', () => {
  const { ids, invalid } = parseGroupIds(` ${GROUP}, 120363111111111111\n972501234567-1600000000@g.us,,abc, 123@s.whatsapp.net`);
  assert.deepEqual([...ids], [GROUP, '120363111111111111@g.us', '972501234567-1600000000@g.us']);
  assert.deepEqual(invalid, ['abc', '123@s.whatsapp.net']);
  assert.equal(parseGroupIds('').ids.size, 0);
  assert.equal(parseGroupIds(undefined).ids.size, 0);
});

test('oneLine: שבירות שורה ותווי שליטה לא עוברים לשורת הלוג, והאורך חסום', () => {
  assert.equal(oneLine('קבוצה\nמזויפת\r\n💬 שורה'), 'קבוצה מזויפת 💬 שורה');
  assert.equal(oneLine('x'.repeat(10), 5), 'xxxx…');
  assert.equal(oneLine(undefined), '');
});

// ===== תוכן =====

test('mapContent: טקסט ומדיה נספרים; פרוטוקול, תגובות וסקרים לא', () => {
  assert.deepEqual(mapContent('conversation', { conversation: 'שלום' }), { type: 'chat', text: 'שלום' });
  assert.deepEqual(mapContent('extendedTextMessage', { extendedTextMessage: { text: 'קישור' } }), {
    type: 'chat',
    text: 'קישור',
  });
  assert.deepEqual(mapContent('imageMessage', { imageMessage: { caption: 'כיתוב' } }), { type: 'image', text: 'כיתוב' });
  assert.deepEqual(mapContent('audioMessage', { audioMessage: { ptt: true } }), { type: 'ptt', text: '' });
  for (const key of ['protocolMessage', 'reactionMessage', 'pollUpdateMessage', undefined]) {
    assert.equal(mapContent(key, {}).type, null, String(key));
  }
});

test('textLength: סופר code points — אמוג׳י הוא תו אחד', () => {
  assert.equal(textLength('שלום'), 4);
  assert.equal(textLength('👍'), 1);
  assert.equal(textLength(undefined), 0);
});

test('phoneFromJids: מספר רק ממזהה טלפון, אף פעם לא מ-LID', () => {
  assert.equal(phoneFromJids('155516504436974@lid', '972541234567@s.whatsapp.net'), '972541234567');
  assert.equal(phoneFromJids('972541234567:3@s.whatsapp.net'), '972541234567');
  assert.equal(phoneFromJids('123405678912345@lid'), null);
  assert.equal(phoneFromJids(GROUP), null);
});

function groupMsg(overrides = {}) {
  return {
    key: { remoteJid: GROUP, id: 'ABC123', fromMe: false, participant: '155516504436974@lid', participantAlt: '972541234567@s.whatsapp.net', ...overrides.key },
    pushName: 'דנה',
    messageTimestamp: 1763030000,
    message: { conversation: 'מחפש מפתח אוטומציות' },
    ...overrides.top,
  };
}

test('toGroupRecord: הודעה מקבוצה — שדות לפי Ck 11.6, עם עזרי Baileys האמיתיים', () => {
  const r = toGroupRecord(groupMsg(), 'notify', helpers);
  assert.deepEqual(r, {
    messageId: 'ABC123',
    groupId: GROUP,
    senderJid: '155516504436974@lid',
    senderPhone: '972541234567',
    senderName: 'דנה',
    type: 'chat',
    text: 'מחפש מפתח אוטומציות',
    timestampSec: 1763030000,
    offline: false,
  });
  assert.equal(toGroupRecord(groupMsg(), 'append', helpers).offline, true);
});

test('toGroupRecord: עטיפות (הודעה נעלמת, צפייה חד-פעמית) נפרסות', () => {
  const msg = groupMsg({ top: { message: { ephemeralMessage: { message: { extendedTextMessage: { text: 'בתוך עטיפה' } } } } } });
  assert.equal(toGroupRecord(msg, 'notify', helpers).text, 'בתוך עטיפה');
});

test('toGroupRecord: פרטי, סטטוס, ערוץ, הודעה שלי, בלי תוכן ובלי מזהה — null', () => {
  const cases = [
    groupMsg({ key: { remoteJid: '972541234567@s.whatsapp.net' } }),
    groupMsg({ key: { remoteJid: '155516504436974@lid' } }),
    groupMsg({ key: { remoteJid: 'status@broadcast' } }),
    groupMsg({ key: { remoteJid: '120363000000000000@newsletter' } }),
    groupMsg({ key: { fromMe: true } }),
    groupMsg({ key: { id: '' } }),
    groupMsg({ top: { message: undefined } }),
    groupMsg({ top: { message: { reactionMessage: { text: '👍' } } } }),
    { key: null },
  ];
  for (const [i, msg] of cases.entries()) assert.equal(toGroupRecord(msg, 'notify', helpers), null, `case ${i}`);
});

test('toGroupRecord: messageTimestamp כ-Long עובר דרך toNumber', () => {
  const longLike = { low: 1763030000, high: 0, toNumber: () => 1763030000 };
  assert.equal(toGroupRecord(groupMsg({ top: { messageTimestamp: longLike } }), 'notify', helpers).timestampSec, 1763030000);
});

// ===== מונים וכפילויות =====

test('claimMessage: רק התופס הראשון מקבל true', () => {
  const s = emptyStats('2026-11-13');
  const key = dedupKey({ groupId: GROUP, messageId: 'X' });
  assert.equal(claimMessage(s, key, 1000), true);
  assert.equal(claimMessage(s, key, 2000), false);
  assert.equal(claimMessage(s, dedupKey({ groupId: GROUP, messageId: 'Y' }), 2000), true);
});

test('recordMessage / rollDay: היומי מתאפס במעבר יום, המצטבר נשמר', () => {
  const s = emptyStats('2026-11-12');
  recordMessage(s, GROUP, true);
  recordMessage(s, GROUP, false);
  assert.equal(rollDay(s, '2026-11-12'), null);
  const summary = rollDay(s, '2026-11-13');
  assert.deepEqual(summary.daily[GROUP], { count: 2, withText: 1 });
  assert.equal(summary.day, '2026-11-12');
  assert.deepEqual(s.daily, {});
  assert.deepEqual(s.totals[GROUP], { count: 2, withText: 1 });
  assert.equal(s.day, '2026-11-13');
  assert.equal(s.since, '2026-11-12');
});

test('pruneSeen: מוחק את מה שעבר את ה-TTL ומשאיר את השאר', () => {
  const s = emptyStats('2026-11-13');
  const now = 100 * SEEN_TTL_MS;
  claimMessage(s, 'old', now - SEEN_TTL_MS - 1);
  claimMessage(s, 'fresh', now - 1000);
  pruneSeen(s, now);
  assert.deepEqual([...s.seen.keys()], ['fresh']);
});

test('claimMessage: התקרה נאכפת בכל תפיסה, לא רק במעבר יום — הישן ביותר יוצא', () => {
  const s = emptyStats('2026-11-13');
  for (let i = 0; i < SEEN_MAX + 5; i++) assert.equal(claimMessage(s, `k${i}`, 1000 + i), true);
  assert.equal(s.seen.size, SEEN_MAX);
  assert.equal(s.seen.has('k0'), false);
  assert.equal(s.seen.has('k4'), false);
  assert.equal(s.seen.has('k5'), true);
  assert.equal(s.seen.has(`k${SEEN_MAX + 4}`), true);
});

test('serializeStats / normalizeStats: הלוך-חזור דרך JSON שומר מזהים, סדר ומונים', () => {
  const s = emptyStats('2026-11-13');
  claimMessage(s, 'b', 2000);
  claimMessage(s, 'a', 1000);
  recordMessage(s, GROUP, true);
  const back = normalizeStats(JSON.parse(JSON.stringify(serializeStats(s))), '2026-11-13');
  assert.deepEqual([...back.seen.entries()], [['a', 1000], ['b', 2000]]); // ממוין לפי זמן — סדר הפינוי
  assert.deepEqual(back.totals[GROUP], { count: 1, withText: 1 });
  assert.equal(claimMessage(back, 'a', 3000), false);
});

test('normalizeStats: קובץ פגום, חלקי או עם NaN לא מכניס זבל למונים', () => {
  assert.deepEqual(normalizeStats(null, '2026-11-13'), emptyStats('2026-11-13'));
  assert.deepEqual(normalizeStats({ version: 2 }, '2026-11-13'), emptyStats('2026-11-13'));
  const n = normalizeStats(
    { version: 1, day: 'bad', since: '2026-11-10', daily: { [GROUP]: { count: 'x', withText: 5 } }, totals: [], seen: { a: 1, b: 'x' } },
    '2026-11-13',
  );
  assert.equal(n.day, '2026-11-13');
  assert.equal(n.since, '2026-11-10');
  assert.deepEqual(n.daily[GROUP], { count: 0, withText: 0 });
  assert.deepEqual(n.totals, {});
  assert.deepEqual([...n.seen.entries()], [['a', 1]]);
});

test('formatDailySummary: כל הקבוצות שבמעקב מופיעות (גם עם 0), עם מצטבר', () => {
  const other = '120363111111111111@g.us';
  const line = formatDailySummary(
    { day: '2026-11-12', since: '2026-11-10', daily: { [GROUP]: { count: 3, withText: 2 } }, totals: { [GROUP]: { count: 9, withText: 7 } } },
    new Set([GROUP, other]),
    (id) => (id === GROUP ? 'פיתוח AI' : undefined),
  );
  assert.match(line, /סיכום יומי 2026-11-12: 3 הודעות, 2 עם טקסט/);
  assert.match(line, /מצטבר מאז 2026-11-10: 9 הודעות, 7 עם טקסט/);
  assert.match(line, /פיתוח AI: 3 \(מצטבר 9\)/);
  assert.match(line, new RegExp(`${other}: 0 \\(מצטבר 0\\)`));
});

// ===== זמן מקומי =====

test('localDayKey / localTime: לפי אזור הזמן, כולל מעבר יום בחצות המקומית', () => {
  // נובמבר: ישראל ב-UTC+2. 22:30Z הוא 00:30 של היום הבא בירושלים.
  const ms = Date.UTC(2026, 10, 13, 22, 30);
  assert.equal(localDayKey(ms, 'Asia/Jerusalem'), '2026-11-14');
  assert.equal(localDayKey(ms, 'UTC'), '2026-11-13');
  assert.equal(localTime(ms, 'Asia/Jerusalem'), '00:30');
});

// ===== טוקן =====

test('safeTokenEqual: התאמה מדויקת בלבד, וטוקן ריק לעולם לא תקף', () => {
  assert.equal(safeTokenEqual('abc', 'abc'), true);
  assert.equal(safeTokenEqual('abc', 'abd'), false);
  assert.equal(safeTokenEqual('abc', 'abcd'), false);
  assert.equal(safeTokenEqual('', ''), false);
  assert.equal(safeTokenEqual(undefined, 'abc'), false);
});

// ===== שומר החיבור =====

test('guardSocket: רק המאפיינים המותרים עוברים; כל השאר זורק לפני שמשהו נקרא', () => {
  let sent = 0;
  const fake = {
    ev: { on() {} },
    groupFetchAllParticipating: async () => ({}),
    end() {},
    sendMessage: () => {
      sent += 1;
    },
    readMessages: () => {
      sent += 1;
    },
  };
  const g = guardSocket(fake);
  assert.equal(typeof g.ev.on, 'function');
  assert.equal(typeof g.groupFetchAllParticipating, 'function');
  assert.throws(() => g.sendMessage('x', { text: 'y' }), ForbiddenSocketAccess);
  assert.throws(() => g.readMessages([]), ForbiddenSocketAccess);
  assert.throws(() => g['send' + 'PresenceUpdate'], ForbiddenSocketAccess);
  assert.throws(() => {
    g.anything = 1;
  }, ForbiddenSocketAccess);
  assert.equal(sent, 0);
  assert.deepEqual([...SOCKET_ALLOWED_PROPS], ['ev', 'groupFetchAllParticipating', 'end']);
});

test('guardSocket: אין דרך עוקפת לחיבור האמיתי — descriptor, keys, delete, defineProperty, prototype', () => {
  const realSend = () => {};
  const fake = { ev: { on() {} }, groupFetchAllParticipating: async () => ({}), end() {}, sendMessage: realSend };
  const g = guardSocket(fake);
  // הדרך שעקפה את get בגרסה הקודמת: ה-descriptor של האובייקט האמיתי
  assert.equal(Object.getOwnPropertyDescriptor(g, 'sendMessage'), undefined);
  assert.deepEqual(Object.keys(g), ['ev', 'groupFetchAllParticipating', 'end']);
  assert.equal('sendMessage' in g, false);
  assert.throws(() => delete g.end, ForbiddenSocketAccess);
  assert.throws(() => Object.defineProperty(g, 'sendMessage', { value: 1 }), ForbiddenSocketAccess);
  assert.throws(() => Object.setPrototypeOf(g, {}), ForbiddenSocketAccess);
  assert.throws(() => ({ ...g }).sendMessage(), TypeError); // העתקה מקבלת רק את המותרים
  // החיבור האמיתי לא השתנה
  assert.equal(fake.sendMessage, realSend);
  assert.equal(typeof fake.end, 'function');
});

test('scrubIdentifiers: מזהי טלפון, LID וקבוצה, ומספרים ארוכים — מוחלפים; קודים קצרים נשארים', () => {
  const out = scrubIdentifiers(
    'from 972541234567@s.whatsapp.net / 155516504436974:12@lid in 120363402840406015@g.us, +972541234567 code=515 id=3EB0A1',
  );
  assert.equal(out, 'from <jid> / <jid> in <jid>, <num> code=515 id=3EB0A1');
  assert.equal(scrubIdentifiers(undefined), '');
});

test('scrubIdentifiers: מספר טלפון מעוצב — רווחים, מקפים, סוגריים, מקף Unicode ותווי כיווניות', () => {
  const formatted = [
    '+972 54-123-4567',
    '054-1234567',
    '(054) 123 4567',
    '054.123.4567',
    '+1 (555) 123-4567',
    '\u2066+972 54\u2011123\u20114567\u2069', // עטוף ב-LRI/PDI, עם מקף שאינו נשבר
    '054\u00a0123\u00a04567', // רווח קשיח
  ];
  for (const t of formatted) {
    const out = scrubIdentifiers(`call ${t} now`);
    assert.ok(!/[0-9](?:\D{0,3}[0-9]){5,}/.test(out), `${JSON.stringify(t)} -> ${JSON.stringify(out)}`);
    assert.match(out, /<num>/);
  }
  // קודים ומספרים קצרים לא נפגעים
  assert.equal(scrubIdentifiers('code 515 status=403 at 127.0.0.1:1, 3 attempts'), 'code 515 status=403 at 127.0.0.1:1, 3 attempts');
});

test('safeText: ניקוי לפני חיתוך — בשום נקודת חיתוך לא נשאר חלק ממספר', () => {
  const phone = '972541234567';
  for (let k = 0; k <= phone.length + 1; k++) {
    const max = 30;
    // המספר מתחיל כך שהחיתוך (max-1 תווים + …) נופל אחרי k ספרות שלו
    const text = `${'x'.repeat(max - 1 - k)}${phone} tail`;
    const out = safeText(text, max);
    assert.ok(!/[0-9]{3,}/.test(out), `k=${k}: ${JSON.stringify(out)}`);
  }
  assert.equal(safeText('קבוצה\nעם 054-1234567', 100), 'קבוצה עם <num>');
});
