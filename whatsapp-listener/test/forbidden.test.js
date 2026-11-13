// המאזין רק קורא. הבדיקה הזו נכשלת אם בקוד של השירות מופיעה אחת הפונקציות
// ששולחות משהו שגלוי לצד השני, או מסמנות את החשבון (Ck, סעיפים 11.7 ו-11.9).
//
// איך: כל קובץ JS של השירות (לא בדיקות ולא node_modules) מפוענח ל-AST עם
// acorn, ונבדקים כל המזהים, שמות המאפיינים ומחרוזות הקוד. הערות לא נבדקות —
// מותר להסביר בהן למה אסור. כך נתפסים גם sock.sendMessage, גם
// sock['sendMessage'] וגם const { sendMessage } = sock.
// מה לא נתפס: הרכבה עקיפה של השם ('send' + 'Message'). לזה יש את השכבה
// השנייה — guardSocket ב-lib.js, שחוסם בזמן ריצה כל מאפיין שאינו ברשימה
// המותרת (ונבדק ב-lib.test.js).

import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { parse } from 'acorn';
import { full } from 'acorn-walk';

const SERVICE_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

// הרשימה מ-Ck 11.7 ו-11.9, בלי יוצא מן הכלל:
//   sendMessage — שליחת הודעה
//   readMessages, sendReceipts — אישור קריאה (וי כחול)
//   sendPresenceUpdate — "מחובר" / "מקליד" / "מקליט"
//   presenceSubscribe — הרשמה לנוכחות של איש קשר
//   chatModify — שינוי מצב צ'אט (ארכיון, סימון)
const FORBIDDEN = ['sendMessage', 'readMessages', 'sendReceipts', 'sendPresenceUpdate', 'presenceSubscribe', 'chatModify'];

function serviceSourceFiles() {
  return fs
    .readdirSync(SERVICE_DIR, { withFileTypes: true })
    .filter((e) => e.isFile() && e.name.endsWith('.js'))
    .map((e) => path.join(SERVICE_DIR, e.name));
}

// חריגים מפורשים, לכל קובץ בנפרד. telegram.js קורא למתודה sendMessage של
// Telegram Bot API (https://core.telegram.org/bots/api#sendmessage) — לא של
// וואטסאפ. הוא לא מייבא את Baileys ולא מקבל את החיבור; הבדיקה למטה מוודאת את זה.
const EXCEPTIONS = { 'telegram.js': new Set(['sendMessage']) };

function parseModule(source) {
  return parse(source, { ecmaVersion: 'latest', sourceType: 'module', locations: true });
}

// מחזיר את כל ההופעות של שמות אסורים בקוד (לא בהערות), עם מספר שורה.
// acorn-walk לא נכנס לשם מאפיין לא-מחושב (sock.X) ולמפתח לא-מחושב
// ({ X } = sock) — base.MemberExpression ו-base.Property ב-walk.mjs עוברים
// עליהם רק כש-computed. לכן הם נבדקים כאן במפורש.
export function findForbidden(source, names = FORBIDDEN) {
  const banned = new Set(names);
  const hits = [];
  const check = (name, node, exact) => {
    if (typeof name !== 'string') return;
    for (const b of banned) {
      // מזהה ושם מאפיין: שוויון מלא. מחרוזת: גם הופעה בתוכה ('sock.sendMessage').
      if (exact ? name === b : name.includes(b)) hits.push({ name: b, line: node.loc.start.line });
    }
  };
  const keyName = (k) => (k && (k.type === 'Identifier' || k.type === 'PrivateIdentifier') ? k.name : null);
  full(parseModule(source), (node) => {
    if (node.type === 'Identifier' || node.type === 'PrivateIdentifier') check(node.name, node, true);
    else if (node.type === 'Literal' && typeof node.value === 'string') check(node.value, node, false);
    else if (node.type === 'TemplateElement') check(node.value.cooked, node, false);
    else if (node.type === 'MemberExpression' && !node.computed) check(keyName(node.property), node.property, true);
    else if (
      (node.type === 'Property' || node.type === 'MethodDefinition' || node.type === 'PropertyDefinition') &&
      !node.computed
    ) {
      check(keyName(node.key), node.key, true);
    }
  });
  return hits;
}

function importSources(source) {
  const out = [];
  full(parseModule(source), (node) => {
    if (node.type === 'ImportDeclaration' || node.type === 'ImportExpression') {
      const src = node.source && node.source.value;
      if (typeof src === 'string') out.push(src);
    }
  });
  return out;
}

test('הסורק עצמו מסוגל להיכשל: תופס קריאה, גישה בסוגריים ופירוק — ומתעלם מהערות', () => {
  const planted = [
    'await sock.sendMessage(jid, { text: "hi" });',
    "sock['readMessages']([key]);",
    'const { sendPresenceUpdate } = sock;',
    'sock.ev.on(`x`, () => sock.chatModify({}, jid));',
    'const k = "sock.presenceSubscribe";',
    'sock.sendReceipts(keys, "read");',
  ];
  for (const src of planted) assert.ok(findForbidden(src).length > 0, `לא נתפס: ${src}`);
  assert.deepEqual(findForbidden('// sock.sendMessage אסור\n/* readMessages */\nconst ok = 1;'), []);
});

test('אין בקוד השירות קריאה לאף פונקציה מרשימת האיסורים', () => {
  const files = serviceSourceFiles();
  // ודאות שהסריקה באמת עוברת על הקבצים המרכזיים, ולא על רשימה ריקה
  for (const required of ['index.js', 'listener.js', 'lib.js', 'telegram.js']) {
    assert.ok(files.some((f) => f.endsWith(path.sep + required)), `${required} לא נסרק`);
  }
  const violations = [];
  for (const file of files) {
    const allowed = EXCEPTIONS[path.basename(file)] || new Set();
    for (const hit of findForbidden(fs.readFileSync(file, 'utf8'))) {
      if (!allowed.has(hit.name)) violations.push(`${path.basename(file)}:${hit.line} — ${hit.name}`);
    }
  }
  assert.deepEqual(violations, [], `פונקציות אסורות בקוד:\n${violations.join('\n')}`);
});

test('קובץ עם חריג לא מגיע לחיבור של וואטסאפ: לא מייבא את Baileys ולא מקבל sock', () => {
  for (const name of Object.keys(EXCEPTIONS)) {
    const source = fs.readFileSync(path.join(SERVICE_DIR, name), 'utf8');
    const imports = importSources(source);
    assert.ok(!imports.some((s) => s.includes('baileys')), `${name} מייבא את Baileys`);
    assert.ok(!imports.some((s) => s.startsWith('./')), `${name} מייבא קובץ פנימי — ייתכן שדרכו מגיע החיבור`);
    assert.deepEqual(findForbidden(source, ['sock']).filter((h) => h.name === 'sock'), [], `${name} נוגע ב-sock`);
  }
});
