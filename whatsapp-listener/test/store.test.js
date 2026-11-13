// טעינת קבצי מצב: קובץ חסר, תקין, פגום, וקובץ שקיים ולא נקרא. הכלל: קובץ
// שלא נקרא לא נדרס — אחרת הכתיבה הבאה מאפסת מונים ומניעת כפילויות.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { loadJsonState, writeJsonAtomic } from '../store.js';

function tmpDir() {
  return fs.mkdtempSync(path.join(os.tmpdir(), 'wa-store-test-'));
}
function quietLog() {
  const lines = [];
  return { lines, info: (m) => lines.push(m), warn: (m) => lines.push(m), error: (m) => lines.push(m) };
}

test('קובץ חסר: ריק, ומותר לכתוב', () => {
  const dir = tmpDir();
  const r = loadJsonState(path.join(dir, 'none.json'), quietLog());
  assert.deepEqual(r, { value: null, status: 'missing', writable: true });
});

test('קובץ תקין: הערך חוזר כמו שנכתב', () => {
  const dir = tmpDir();
  const file = path.join(dir, 's.json');
  writeJsonAtomic(file, { a: 1 });
  assert.deepEqual(loadJsonState(file, quietLog()), { value: { a: 1 }, status: 'ok', writable: true });
});

test('קובץ פגום: מועבר הצידה ולא נמחק, ומתחילים ריק', () => {
  const dir = tmpDir();
  const file = path.join(dir, 's.json');
  fs.writeFileSync(file, '{"version":1, "seen": {');
  const r = loadJsonState(file, quietLog(), 12345);
  assert.deepEqual(r, { value: null, status: 'corrupt', writable: true });
  assert.equal(fs.existsSync(file), false);
  assert.equal(fs.readFileSync(`${file}.corrupt-12345`, 'utf8'), '{"version":1, "seen": {');
});

test('קובץ שקיים ולא נקרא (כאן: תיקייה במקום קובץ, EISDIR): writable=false, ושום דבר לא נמחק', () => {
  // EACCES אי אפשר לשחזר כ-root (ההרשאות לא נאכפות עליו). EISDIR היא שגיאת
  // קריאה אמיתית שאינה ENOENT — אותו מסלול בקוד.
  const dir = tmpDir();
  const file = path.join(dir, 's.json');
  fs.mkdirSync(file);
  fs.writeFileSync(path.join(file, 'keep.txt'), 'x');
  const log = quietLog();
  const r = loadJsonState(file, log);
  assert.deepEqual(r, { value: null, status: 'unreadable', writable: false });
  assert.equal(fs.readFileSync(path.join(file, 'keep.txt'), 'utf8'), 'x');
  assert.match(log.lines[0], /לא אכתוב עליו/);
});
