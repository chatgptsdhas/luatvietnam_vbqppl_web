'use strict';
/**
 * Chứng minh hành vi thật (không phải static grep) của cơ chế quản lý Script Properties P0:
 * installP0ScriptPropertyDefaults / auditP0ScriptProperties / requireP0ScriptProperties_ trong
 * apps_script/Security.js — không ghi đè property có sẵn, không tạo placeholder cho secret,
 * không log/trả giá trị secret, và không gọi được qua doPost (WebApp.js).
 *
 * Mô phỏng môi trường Apps Script bằng Node vm, cùng kiểu harness với
 * test_webapp_security_boundaries.js.
 *
 * Chạy: node tests/test_p0_script_property_management.js
 */
const fs = require('fs');
const vm = require('vm');
const crypto = require('crypto');
const assert = require('assert');

const SECURITY_SRC = fs.readFileSync(__dirname + '/../apps_script/Security.js', 'utf8');
const WEBAPP_SRC = fs.readFileSync(__dirname + '/../apps_script/WebApp.js', 'utf8');

function computeHmacSha256Signature(messageBytesOrStr, keyBytesOrStr) {
  const msgBuf = Buffer.isBuffer(messageBytesOrStr) || Array.isArray(messageBytesOrStr)
    ? Buffer.from(messageBytesOrStr.map(b => b < 0 ? b + 256 : b))
    : Buffer.from(String(messageBytesOrStr), 'utf8');
  const keyBuf = Buffer.isBuffer(keyBytesOrStr) || Array.isArray(keyBytesOrStr)
    ? Buffer.from(keyBytesOrStr.map(b => b < 0 ? b + 256 : b))
    : Buffer.from(String(keyBytesOrStr), 'utf8');
  const digest = crypto.createHmac('sha256', keyBuf).update(msgBuf).digest();
  return Array.from(digest).map(b => (b > 127 ? b - 256 : b));
}
function computeDigest(_algorithm, messageStr) {
  const digest = crypto.createHash('sha256').update(Buffer.from(String(messageStr), 'utf8')).digest();
  return Array.from(digest).map(b => (b > 127 ? b - 256 : b));
}
function pad(n) { return String(n).padStart(2, '0'); }
function formatDate(date, _tz, pattern) {
  const map = { dd: pad(date.getDate()), MM: pad(date.getMonth() + 1), yyyy: String(date.getFullYear()), HH: pad(date.getHours()), mm: pad(date.getMinutes()), ss: pad(date.getSeconds()) };
  return pattern.replace(/yyyy/g, map.yyyy).replace(/MM/g, map.MM).replace(/dd/g, map.dd).replace(/HH/g, map.HH).replace(/mm/g, map.mm).replace(/ss/g, map.ss);
}

function makeSheet(name) {
  return {
    name, data: [],
    appendRow(rowArr) { this.data.push(rowArr.slice()); },
    getRange() { return { getValues: () => [], setValues() {}, setValue() {}, getValue: () => '' }; },
    getLastRow() { return this.data.length; },
    getLastColumn() { return this.data.length ? this.data[0].length : 0; }
  };
}
function makeSpreadsheet() {
  const sheets = {};
  return { sheets, getSheetByName(n) { return sheets[n] || null; }, insertSheet(n) { const s = makeSheet(n); sheets[n] = s; return s; } };
}

const scriptProps = {};
const ss = makeSpreadsheet();

const ctx = {
  console,
  SpreadsheetApp: { getActiveSpreadsheet() { return ss; }, flush() {} },
  Utilities: {
    newBlob(input) {
      const buf = Array.isArray(input) ? Buffer.from(input.map(b => (b < 0 ? b + 256 : b))) : Buffer.from(String(input), 'utf8');
      return { getBytes() { return Array.from(buf).map(b => (b > 127 ? b - 256 : b)); }, getDataAsString() { return buf.toString('utf8'); } };
    },
    formatDate,
    computeHmacSha256Signature, computeDigest,
    DigestAlgorithm: { SHA_256: 'SHA_256' },
    getUuid() { return 'uuid-' + crypto.randomBytes(8).toString('hex'); },
    base64EncodeWebSafe(str) { return Buffer.from(String(str), 'utf8').toString('base64').replace(/\+/g, '-').replace(/\//g, '_'); },
    base64DecodeWebSafe(str) {
      let s = String(str).replace(/-/g, '+').replace(/_/g, '/');
      return Array.from(Buffer.from(s, 'base64')).map(b => (b > 127 ? b - 256 : b));
    },
    Charset: { UTF_8: 'UTF_8' }
  },
  Session: { getScriptTimeZone() { return 'Asia/Ho_Chi_Minh'; } },
  PropertiesService: {
    getScriptProperties() {
      return {
        getProperty(k) { return Object.prototype.hasOwnProperty.call(scriptProps, k) ? scriptProps[k] : null; },
        setProperty(k, v) { scriptProps[k] = v; },
        deleteProperty(k) { delete scriptProps[k]; }
      };
    }
  },
  ScriptApp: { getProjectTriggers() { return []; }, newTrigger() { return { timeBased() { return this; }, everyDays() { return this; }, atHour() { return this; }, create() { return {}; } }; }, deleteTrigger() {} },
  LockService: { getScriptLock() { return { tryLock() { return true; }, releaseLock() {} }; } },
  Logger: { log() {} },
  ContentService: {
    MimeType: { JSON: 'JSON' },
    createTextOutput(text) { return { _text: text, setMimeType() { return this; }, getContent() { return this._text; } }; }
  }
};
ctx.global = ctx;
vm.createContext(ctx);
vm.runInContext(SECURITY_SRC, ctx, { filename: 'Security.js' });
vm.runInContext(WEBAPP_SRC, ctx, { filename: 'WebApp.js' });

const SCHEMA_OBJ = vm.runInContext('P0_SCRIPT_PROPERTY_SCHEMA_', ctx);
const SCHEMA_KEYS = Object.keys(SCHEMA_OBJ);
const SECRET_KEYS = SCHEMA_KEYS.filter(k => SCHEMA_OBJ[k].secret);
const SAFE_DEFAULT_KEYS = SCHEMA_KEYS.filter(k => !SCHEMA_OBJ[k].secret);

let pass = 0, fail = 0;
function check(name, fn) {
  try { fn(); console.log('PASS -', name); pass++; }
  catch (e) { console.log('FAIL -', name, '=>', e.message); fail++; }
}

function clearProps() { Object.keys(scriptProps).forEach(k => delete scriptProps[k]); }

// vm.createContext gives objects created inside the sandbox (arrays included) their own Realm,
// so Array.prototype differs from the host's — assert.deepStrictEqual then fails on structurally
// identical arrays because it also checks prototype identity. Round-trip through JSON to normalize
// into plain host-realm values before deep-comparing.
function plain(value) { return JSON.parse(JSON.stringify(value)); }

const REAL_SECRET_VALUES = {
  APPS_SCRIPT_TOKEN: 'DISTINCTIVE-PUBLIC-TOKEN-VALUE',
  APPS_SCRIPT_SERVICE_TOKEN: 'DISTINCTIVE-SERVICE-TOKEN-VALUE',
  ADMIN_PASSWORD_SALT: 'DISTINCTIVE-SALT-HEXVALUE',
  ADMIN_PASSWORD_HASH: 'DISTINCTIVE-HASH-HEXVALUE',
  ADMIN_SESSION_SECRET: 'DISTINCTIVE-SESSION-SECRET-VALUE',
  PLANNER_SYNC_SHARED_SECRET: 'DISTINCTIVE-PLANNER-SHARED-SECRET'
};

function setAllValidProperties() {
  clearProps();
  Object.keys(REAL_SECRET_VALUES).forEach(k => { scriptProps[k] = REAL_SECRET_VALUES[k]; });
  scriptProps.ADMIN_PASSWORD_ITERATIONS = '210000';
  scriptProps.ADMIN_SESSION_TTL_SECONDS = '900';
  scriptProps.PLANNER_SYNC_REQUEST_TTL_SECONDS = '300';
  scriptProps.WEBAPP_LOG_VERBOSE_DEBUG = 'false';
}

// ============================================================
// installP0ScriptPropertyDefaults
// ============================================================
check('install trên property rỗng: set đúng 4 default an toàn, không đụng 6 secret', () => {
  clearProps();
  const result = plain(ctx.installP0ScriptPropertyDefaults());
  assert.strictEqual(result.ok, true);
  assert.deepStrictEqual(result.defaults_created.slice().sort(), SAFE_DEFAULT_KEYS.slice().sort());
  assert.deepStrictEqual(result.defaults_preserved, []);
  assert.deepStrictEqual(result.missing_required_secrets.slice().sort(), SECRET_KEYS.slice().sort());
  assert.strictEqual(scriptProps.ADMIN_PASSWORD_ITERATIONS, '210000');
  assert.strictEqual(scriptProps.ADMIN_SESSION_TTL_SECONDS, '900');
  assert.strictEqual(scriptProps.PLANNER_SYNC_REQUEST_TTL_SECONDS, '300');
  assert.strictEqual(scriptProps.WEBAPP_LOG_VERBOSE_DEBUG, 'false');
  SECRET_KEYS.forEach(k => assert.strictEqual(scriptProps[k], undefined, `install không được set secret ${k}`));
});

check('install KHÔNG ghi đè property đã có giá trị tuỳ chỉnh', () => {
  clearProps();
  scriptProps.ADMIN_SESSION_TTL_SECONDS = '1800'; // giá trị tuỳ chỉnh, khác default 900
  const result = plain(ctx.installP0ScriptPropertyDefaults());
  assert.ok(result.defaults_preserved.indexOf('ADMIN_SESSION_TTL_SECONDS') !== -1);
  assert.ok(result.defaults_created.indexOf('ADMIN_SESSION_TTL_SECONDS') === -1);
  assert.strictEqual(scriptProps.ADMIN_SESSION_TTL_SECONDS, '1800', 'Không được ghi đè giá trị tuỳ chỉnh đã có');
});

check('install không xoá hoặc động tới property ngoài schema (vd INTRO_LOGIN)', () => {
  clearProps();
  scriptProps.INTRO_LOGIN = 'gia-tri-intro-hien-co';
  scriptProps.INTRO_SOME_OTHER_FLAG = 'x';
  ctx.installP0ScriptPropertyDefaults();
  assert.strictEqual(scriptProps.INTRO_LOGIN, 'gia-tri-intro-hien-co');
  assert.strictEqual(scriptProps.INTRO_SOME_OTHER_FLAG, 'x');
});

check('install chạy 2 lần liên tiếp là idempotent (không tạo lại/đổi giá trị đã set)', () => {
  clearProps();
  ctx.installP0ScriptPropertyDefaults();
  const snapshot = Object.assign({}, scriptProps);
  const second = plain(ctx.installP0ScriptPropertyDefaults());
  assert.deepStrictEqual(scriptProps, snapshot);
  assert.deepStrictEqual(second.defaults_preserved.slice().sort(), SAFE_DEFAULT_KEYS.slice().sort());
  assert.deepStrictEqual(second.defaults_created, []);
});

// ============================================================
// auditP0ScriptProperties
// ============================================================
check('audit trên property rỗng: 10/10 missing, ok=false', () => {
  clearProps();
  const audit = plain(ctx.auditP0ScriptProperties());
  assert.strictEqual(audit.ok, false);
  assert.strictEqual(audit.configured.length, 0);
  assert.strictEqual(audit.missing.length, SCHEMA_KEYS.length);
  assert.strictEqual(audit.invalid.length, 0);
});

check('audit khi tất cả 10 property hợp lệ -> ok=true, configured đủ 10, missing/invalid rỗng', () => {
  setAllValidProperties();
  const audit = plain(ctx.auditP0ScriptProperties());
  assert.strictEqual(audit.ok, true, JSON.stringify(audit));
  assert.strictEqual(audit.configured.length, SCHEMA_KEYS.length);
  assert.deepStrictEqual(audit.missing, []);
  assert.deepStrictEqual(audit.invalid, []);
});

check('audit phát hiện ADMIN_PASSWORD_ITERATIONS < 100000 là invalid', () => {
  setAllValidProperties();
  scriptProps.ADMIN_PASSWORD_ITERATIONS = '50000';
  const audit = plain(ctx.auditP0ScriptProperties());
  assert.strictEqual(audit.ok, false);
  assert.ok(audit.invalid.some(item => item.key === 'ADMIN_PASSWORD_ITERATIONS'), JSON.stringify(audit.invalid));
});

check('audit phát hiện WEBAPP_LOG_VERBOSE_DEBUG không phải true/false là invalid', () => {
  setAllValidProperties();
  scriptProps.WEBAPP_LOG_VERBOSE_DEBUG = 'yes';
  const audit = plain(ctx.auditP0ScriptProperties());
  assert.strictEqual(audit.ok, false);
  assert.ok(audit.invalid.some(item => item.key === 'WEBAPP_LOG_VERBOSE_DEBUG'), JSON.stringify(audit.invalid));
});

check('audit phát hiện ADMIN_SESSION_TTL_SECONDS / PLANNER_SYNC_REQUEST_TTL_SECONDS không phải số nguyên dương', () => {
  setAllValidProperties();
  scriptProps.ADMIN_SESSION_TTL_SECONDS = '-5';
  scriptProps.PLANNER_SYNC_REQUEST_TTL_SECONDS = 'abc';
  const audit = plain(ctx.auditP0ScriptProperties());
  assert.strictEqual(audit.ok, false);
  const invalidKeys = audit.invalid.map(i => i.key);
  assert.ok(invalidKeys.indexOf('ADMIN_SESSION_TTL_SECONDS') !== -1);
  assert.ok(invalidKeys.indexOf('PLANNER_SYNC_REQUEST_TTL_SECONDS') !== -1);
});

check('audit KHÔNG BAO GIỜ trả về giá trị secret thật (kể cả khi tất cả đã set)', () => {
  setAllValidProperties();
  const audit = plain(ctx.auditP0ScriptProperties());
  const serialized = JSON.stringify(audit);
  Object.keys(REAL_SECRET_VALUES).forEach(key => {
    const secretValue = REAL_SECRET_VALUES[key];
    assert.ok(serialized.indexOf(secretValue) === -1, `audit làm lộ giá trị secret của ${key}: ${serialized}`);
  });
});

// ============================================================
// requireP0ScriptProperties_
// ============================================================
check('requireP0ScriptProperties_ throw P0_SCRIPT_PROPERTIES_INVALID khi thiếu cấu hình, message chỉ có tên property', () => {
  clearProps();
  scriptProps.APPS_SCRIPT_TOKEN = REAL_SECRET_VALUES.APPS_SCRIPT_TOKEN; // set 1 phần, còn thiếu nhiều
  let threw = false, code = '', message = '';
  try { ctx.requireP0ScriptProperties_(); } catch (e) { threw = true; code = e.name; message = e.message; }
  assert.strictEqual(threw, true);
  assert.strictEqual(code, 'P0_SCRIPT_PROPERTIES_INVALID');
  assert.ok(message.indexOf('ADMIN_SESSION_SECRET') !== -1, 'message phải liệt kê tên property thiếu');
  assert.ok(message.indexOf(REAL_SECRET_VALUES.APPS_SCRIPT_TOKEN) === -1, 'message không được chứa giá trị secret thật');
});

check('requireP0ScriptProperties_ KHÔNG throw khi cấu hình đầy đủ và hợp lệ', () => {
  setAllValidProperties();
  const result = ctx.requireP0ScriptProperties_();
  assert.strictEqual(result.ok, true);
});

// ============================================================
// Không lộ qua doPost dưới bất kỳ token nào
// ============================================================
function makeEvent(body) { return { postData: { contents: JSON.stringify(body) } }; }
function callDoPost(body) { const res = ctx.doPost(makeEvent(body)); return JSON.parse(res.getContent()); }

['installP0ScriptPropertyDefaults','auditP0ScriptProperties','runAuditP0ScriptProperties','requireP0ScriptProperties_'].forEach((action) => {
  check(`doPost('${action}') -> ACTION_NOT_SUPPORTED (chỉ chạy thủ công trong Apps Script Editor)`, () => {
    setAllValidProperties();
    const res = callDoPost({ token: REAL_SECRET_VALUES.APPS_SCRIPT_TOKEN, action, payload: {} });
    assert.strictEqual(res.ok, false);
    assert.strictEqual(res.error, 'ACTION_NOT_SUPPORTED', `"${action}" không được lộ qua doPost: ${JSON.stringify(res)}`);
  });

  check(`doPost('${action}') với service_token đúng cũng vẫn -> ACTION_NOT_SUPPORTED`, () => {
    setAllValidProperties();
    const res = callDoPost({ token: REAL_SECRET_VALUES.APPS_SCRIPT_TOKEN, service_token: REAL_SECRET_VALUES.APPS_SCRIPT_SERVICE_TOKEN, action, payload: {} });
    assert.strictEqual(res.error, 'ACTION_NOT_SUPPORTED');
  });
});

console.log('\n----------------------------------------');
console.log(`TOTAL: ${pass + fail}, PASS: ${pass}, FAIL: ${fail}`);
process.exit(fail > 0 ? 1 : 0);
