// השומר מול אובייקט חיבור אמיתי של Baileys, לא מול דמות: הפונקציות האסורות
// באמת קיימות עליו, והשומר חוסם את כולן; המאפיינים המותרים עובדים דרכו
// (כולל אירועים אמיתיים מ-ev ו-end). החיבור מכוון לפורט סגור ב-localhost,
// כך ששום דבר לא יוצא לשרתי וואטסאפ.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import pino from 'pino';
import makeWASocket, { makeCacheableSignalKeyStore, useMultiFileAuthState } from '@whiskeysockets/baileys';
import { ForbiddenSocketAccess, guardSocket, SOCKET_ALLOWED_PROPS } from '../lib.js';

// הרשימה מ-Ck 11.7/11.9, ועוד שתי פונקציות שליחה ברמה נמוכה יותר
// (lib/Socket/messages-send.js: relayMessage, sendReceipt).
const SENDING = [
  'sendMessage',
  'readMessages',
  'sendReceipts',
  'sendPresenceUpdate',
  'presenceSubscribe',
  'chatModify',
  'relayMessage',
  'sendReceipt',
];

test('guardSocket על חיבור Baileys אמיתי: חוסם כל פונקציית שליחה, ומעביר ev/end', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'wa-auth-test-'));
  const logger = pino({ level: 'silent' });
  const auth = await useMultiFileAuthState(dir);
  const raw = makeWASocket({
    waWebSocketUrl: 'ws://127.0.0.1:1',
    version: [2, 3000, 1043857760],
    browser: ['Mac OS', 'Chrome', '14.4.1'],
    auth: { creds: auth.state.creds, keys: makeCacheableSignalKeyStore(auth.state.keys, logger) },
    logger,
    markOnlineOnConnect: false,
  });
  try {
    const sock = guardSocket(raw);
    for (const name of SENDING) {
      assert.equal(typeof raw[name], 'function', `${name} לא קיימת בגרסה הזו — הרשימה התיישנה`);
      assert.throws(() => sock[name], ForbiddenSocketAccess, name);
    }
    for (const name of SOCKET_ALLOWED_PROPS) assert.notEqual(sock[name], undefined, name);

    const events = [];
    const closed = new Promise((resolve) => {
      sock.ev.on('connection.update', (u) => {
        if (u.connection) events.push(u.connection);
        if (u.connection === 'close') resolve();
      });
    });
    await closed; // הפורט סגור — החיבור נכשל ונסגר מעצמו
    assert.deepEqual(events, ['connecting', 'close']);
  } finally {
    await raw.end(undefined);
    fs.rmSync(dir, { recursive: true, force: true });
  }
});
