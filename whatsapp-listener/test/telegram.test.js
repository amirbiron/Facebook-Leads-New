// בדיקות להתראות טלגרם: הטוקן לא יוצא בשום הודעת שגיאה, כשל לא נבלע
// כהצלחה (K11), וההודעה נשלחת כטקסט רגיל בלי parse_mode.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createNotifier, redactToken, telegramSendMessage, TelegramSendError } from '../telegram.js';

const TOKEN = '123456789:AAHsecretPartOfTheBotTokenXYZ';
const SECRET = 'AAHsecretPartOfTheBotTokenXYZ';

function jsonResponse(status, body) {
  return { ok: status >= 200 && status < 300, status, json: async () => body };
}

test('redactToken: מסיר את מקטע /bot<token> ואת הטוקן עצמו', () => {
  const s = `request to https://api.telegram.org/bot${TOKEN}/sendMessage failed; token=${TOKEN}`;
  const out = redactToken(s, TOKEN);
  assert.ok(!out.includes(SECRET));
  assert.match(out, /\/bot<TOKEN>\/sendMessage/);
});

test('redactToken: נכשל-סגור — אם החלק הסודי נשאר בצורה אחרת, כל הטקסט מוסתר', () => {
  const out = redactToken(`encoded: bot123456789%3A${SECRET}`, TOKEN);
  assert.ok(!out.includes(SECRET));
  assert.match(out, /הוסתרה/);
});

test('telegramSendMessage: שולח לכתובת הנכונה, טקסט רגיל בלי parse_mode', async () => {
  let call;
  const body = await telegramSendMessage({
    token: TOKEN,
    chatId: '42',
    text: 'שלום *לא עיצוב* _x_',
    fetchImpl: async (url, init) => {
      call = { url, init };
      return jsonResponse(200, { ok: true, result: { message_id: 1 } });
    },
  });
  assert.equal(body.ok, true);
  assert.equal(call.url, `https://api.telegram.org/bot${TOKEN}/sendMessage`);
  assert.equal(call.init.method, 'POST');
  const sent = JSON.parse(call.init.body);
  assert.deepEqual(sent, { chat_id: '42', text: 'שלום *לא עיצוב* _x_' });
});

test('telegramSendMessage: סטטוס שאינו 2xx זורק, עם תיאור טלגרם ובלי הטוקן', async () => {
  await assert.rejects(
    telegramSendMessage({
      token: TOKEN,
      chatId: '42',
      text: 'x',
      fetchImpl: async () => jsonResponse(401, { ok: false, error_code: 401, description: 'Unauthorized' }),
    }),
    (err) => err instanceof TelegramSendError && err.status === 401 && /Unauthorized/.test(err.message) && !err.message.includes(SECRET),
  );
});

test('telegramSendMessage: 200 עם ok:false הוא כשל, לא הצלחה', async () => {
  await assert.rejects(
    telegramSendMessage({ token: TOKEN, chatId: '42', text: 'x', fetchImpl: async () => jsonResponse(200, { ok: false }) }),
    TelegramSendError,
  );
});

test('telegramSendMessage: שגיאת רשת שמכילה את הכתובת — יוצאת מנוקה, בלי cause ובלי stack של המקורית', async () => {
  const original = new TypeError(`Failed to parse URL from https://api.telegram.org/bot${TOKEN}/sendMessage`);
  original.cause = new Error(`connect ECONNREFUSED for /bot${TOKEN}/sendMessage`);
  try {
    await telegramSendMessage({
      token: TOKEN,
      chatId: '42',
      text: 'x',
      fetchImpl: async () => {
        throw original;
      },
    });
    assert.fail('expected rejection');
  } catch (err) {
    assert.ok(err instanceof TelegramSendError);
    assert.equal(err.cause, undefined);
    const everything = [err.message, err.stack, String(err)].join('\n');
    assert.ok(!everything.includes(SECRET), everything);
    assert.match(err.message, /TypeError/);
  }
});

test('createNotifier: כשל לא נבלע כהצלחה, והלוג בלי הטוקן', async () => {
  const logs = [];
  const log = { info() {}, warn() {}, error: (m) => logs.push(m) };
  const n = createNotifier({
    token: TOKEN,
    chatId: '42',
    log,
    fetchImpl: async () => {
      throw new Error(`boom at /bot${TOKEN}/sendMessage`);
    },
  });
  assert.equal(await n.send('x'), false);
  assert.equal(logs.length, 1);
  assert.ok(!logs[0].includes(SECRET));
});

test('createNotifier: בלי טוקן או צ׳אט — לא שולח, כותב ללוג ומחזיר false', async () => {
  const logs = [];
  let called = 0;
  const n = createNotifier({
    token: '',
    chatId: '42',
    log: { error: (m) => logs.push(m) },
    fetchImpl: async () => {
      called += 1;
    },
  });
  assert.equal(n.enabled, false);
  assert.equal(await n.send('התראה'), false);
  assert.equal(called, 0);
  assert.match(logs[0], /התראה/);
});
