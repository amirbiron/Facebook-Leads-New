// index.js עצמו, כתהליך אמיתי: החיווט שהבדיקות האחרות לא מגיעות אליו —
// האזנה על localhost כברירת מחדל, /qr סגור בלי טוקן, כיבוי מסודר, וקובץ
// מונים שקיים ולא נקרא שלא נדרס. בלי סשן מקושר השירות לא פותח חיבור
// לוואטסאפ, ובלי משתני טלגרם ההתראות נכתבות ללוג — כך ששום דבר לא יוצא החוצה.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const SERVICE_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

function runService(env) {
  const child = spawn(process.execPath, ['index.js'], {
    cwd: SERVICE_DIR,
    env: { PATH: process.env.PATH, ...env }, // בלי TELEGRAM_* — שום התראה לא יוצאת
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  let out = '';
  child.stdout.on('data', (d) => (out += d));
  child.stderr.on('data', (d) => (out += d));
  const waitFor = (needle, ms = 10000) =>
    new Promise((resolve, reject) => {
      const started = Date.now();
      const tick = () => {
        if (out.includes(needle)) return resolve();
        if (Date.now() - started > ms) return reject(new Error(`timeout waiting for "${needle}"\n${out}`));
        setTimeout(tick, 50);
      };
      tick();
    });
  const stop = () =>
    new Promise((resolve) => {
      child.on('exit', (code) => resolve(code));
      child.kill('SIGTERM');
    });
  return { child, waitFor, stop, output: () => out };
}

const randomPort = () => 20000 + Math.floor(Math.random() * 20000);

test('index.js: localhost כברירת מחדל, /qr סגור בלי טוקן, כיבוי מסודר שכותב את המונים', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'wa-index-'));
  const port = randomPort();
  const svc = runService({ PORT: String(port), WA_AUTH_DIR: path.join(dir, 'auth'), WA_GROUP_IDS: '120363402840406015@g.us' });
  try {
    await svc.waitFor(`127.0.0.1:${port}`);
    await svc.waitFor('needs_pairing');
    const root = await fetch(`http://127.0.0.1:${port}/`);
    assert.equal(root.status, 200);
    assert.equal(await root.text(), 'ok');
    assert.equal((await fetch(`http://127.0.0.1:${port}/qr`)).status, 404);
    assert.equal((await fetch(`http://127.0.0.1:${port}/qr?token=whatever`)).status, 404);
  } finally {
    assert.equal(await svc.stop(), 0);
  }
  const saved = JSON.parse(fs.readFileSync(path.join(dir, 'wa-listener-stats.json'), 'utf8'));
  assert.equal(saved.version, 1);
  assert.deepEqual(saved.seen, {});
  fs.rmSync(dir, { recursive: true, force: true });
});

test('index.js: קובץ מונים שקיים ולא נקרא — לא נדרס, ונשלחת התראה (כאן ללוג)', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'wa-index-'));
  // תיקייה במקום הקובץ: הקריאה נכשלת ב-EISDIR, כמו קובץ שאין הרשאה לקרוא
  const statsPath = path.join(dir, 'wa-listener-stats.json');
  fs.mkdirSync(statsPath);
  fs.writeFileSync(path.join(statsPath, 'keep.txt'), 'x');
  const port = randomPort();
  const svc = runService({ PORT: String(port), WA_AUTH_DIR: path.join(dir, 'auth') });
  try {
    await svc.waitFor('needs_pairing');
  } finally {
    assert.equal(await svc.stop(), 0);
  }
  const out = svc.output();
  assert.match(out, /לא אכתוב עליו/);
  assert.match(out, /קובץ המונים קיים אבל לא נקרא/);
  assert.ok(!out.includes('שמירת המונים נכשלה'), 'ניסה לכתוב על קובץ שלא נקרא');
  assert.equal(fs.readFileSync(path.join(statsPath, 'keep.txt'), 'utf8'), 'x');
  fs.rmSync(dir, { recursive: true, force: true });
});
