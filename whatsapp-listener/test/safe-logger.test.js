// הלוגר שמועבר ל-Baileys: מה שיוצא ממנו לא מכיל מזהי שולח, צמתים גולמיים
// או שם החשבון — גם כשהספרייה מעבירה אותם. הקריאות כאן משחזרות קריאות
// אמיתיות מקוד המקור של 7.0.0-rc14 (המיקום ליד כל אחת).

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createSafeLogger, sanitizeFields } from '../safe-logger.js';

function capture(level = 'trace') {
  const lines = [];
  const logger = createSafeLogger({ level, write: (l) => lines.push(l) });
  return { logger, lines, text: () => lines.join('\n') };
}

const PHONE = '972541234567';
const LID = '155516504436974';

test('decode-wa-message.js:288-296 — "failed to decrypt message" יוצא בלי key/sender/author', () => {
  const { logger, lines, text } = capture();
  logger.error(
    {
      key: { remoteJid: '120363402840406015@g.us', participant: `${LID}@lid`, id: 'ABC' },
      err: Object.assign(new Error(`No session for ${PHONE}@s.whatsapp.net`), { name: 'SessionError' }),
      messageType: 'pkmsg',
      sender: `${PHONE}@s.whatsapp.net`,
      author: `${LID}@lid`,
      isSessionRecordError: true,
    },
    'failed to decrypt message',
  );
  assert.equal(lines.length, 1);
  const rec = JSON.parse(lines[0].replace(/^\[baileys\] /, ''));
  assert.equal(rec.level, 'error');
  assert.equal(rec.msg, 'failed to decrypt message');
  assert.equal(rec.messageType, 'pkmsg');
  assert.equal(rec.isSessionRecordError, true);
  assert.match(rec.err, /^SessionError: No session for <jid>$/);
  assert.equal(rec.dropped, 'key,sender,author');
  assert.ok(!text().includes(PHONE) && !text().includes(LID), text());
});

test('צומת גולמי (node) ושדות לא מוכרים נשמטים — רק השם שלהם נרשם', () => {
  const { logger, text } = capture();
  logger.warn({ node: `<message from="${PHONE}@s.whatsapp.net"/>`, fromJid: `${LID}@lid` }, 'invalid mex newsletter notification');
  assert.match(text(), /"dropped":"node,fromJid"/);
  assert.ok(!text().includes(PHONE) && !text().includes(LID));
});

test('socket.js:847 — pushName (השם האישי) בשדה name לא יוצא', () => {
  const { logger, text } = capture();
  logger.debug({ name: 'דנה כהן' }, 'updated pushName');
  assert.ok(!text().includes('דנה'));
});

test('מזהה בתוך ההודעה עצמה ובתוך trace — מוחלף', () => {
  const { logger, text } = capture();
  logger.info({ trace: `Error: x ${PHONE}@s.whatsapp.net\n    at f (file.js:1:1)` }, `handled for ${LID}@lid`);
  assert.ok(!text().includes(PHONE) && !text().includes(LID));
  assert.ok(!text().includes('file.js'), 'trace מקוצר לשורה הראשונה');
});

test('רמה: מתחת לסף לא נכתב; child מסנן את ה-bindings; level נחשף לבדיקות של Baileys', () => {
  const { logger, lines } = capture('warn');
  assert.equal(logger.level, 'warn');
  logger.info('info is below warn');
  logger.debug({ a: 1 }, 'debug');
  assert.equal(lines.length, 0);
  const child = logger.child({ class: 'baileys', jid: `${PHONE}@s.whatsapp.net` });
  assert.equal(child.level, 'warn');
  child.warn('hello');
  assert.equal(lines.length, 1);
  assert.match(lines[0], /"class":"baileys"/);
  assert.ok(!lines[0].includes(PHONE));
});

test('Error כארגומנט ראשון, ומחרוזת בלבד — שתי הצורות של ILogger', () => {
  const { logger, lines } = capture();
  logger.error(new Error(`boom ${PHONE}`));
  logger.warn('plain message');
  assert.match(lines[0], /"err":"Error: boom <num>"/);
  assert.match(lines[1], /"msg":"plain message"/);
});

test('silent / רמה לא מוכרת: silent לא כותב כלום; רמה לא מוכרת נופלת ל-warn', () => {
  const s = capture('silent');
  s.logger.error('x');
  assert.equal(s.lines.length, 0);
  const u = capture('nonsense');
  assert.equal(u.logger.level, 'warn');
});

test('sanitizeFields: אובייקט בשדה מותר לא נפתח', () => {
  const { fields, dropped } = sanitizeFields({ type: { participant: `${PHONE}@s.whatsapp.net` }, count: 3 });
  assert.deepEqual(fields, { count: 3 });
  assert.deepEqual(dropped, ['type']);
});
