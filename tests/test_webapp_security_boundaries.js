'use strict';
/**
 * Chứng minh: APPS_SCRIPT_TOKEN (token công khai, nhúng trong Dashboard/index.html) KHÔNG thể
 * tự nó gọi được bất kỳ action nhóm B (service) hay nhóm C (admin/write) nào trong
 * apps_script/WebApp.js, và các hàm bảo trì (repair/maintenance) hoàn toàn không lộ ra qua
 * doPost — bất kể token nào.
 *
 * Đây là test hành vi thật (chạy doPost() thật, không phải static grep) — mô phỏng môi trường
 * Apps Script bằng Node vm + các API tối thiểu (SpreadsheetApp/PropertiesService/Utilities...).
 *
 * Chạy: node tests/test_webapp_security_boundaries.js
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

function makeRange(sheet, row, col, numRows, numCols) {
  return {
    getValues() {
      const out = [];
      for (let r = 0; r < numRows; r++) {
        const rowArr = [];
        const src = sheet.data[row - 1 + r] || [];
        for (let c = 0; c < numCols; c++) rowArr.push(src[col - 1 + c] !== undefined ? src[col - 1 + c] : '');
        out.push(rowArr);
      }
      return out;
    },
    getValue() { const r = sheet.data[row - 1] || []; return r[col - 1] !== undefined ? r[col - 1] : ''; },
    setValues(values) {
      for (let r = 0; r < values.length; r++) {
        while (sheet.data.length < row + r) sheet.data.push([]);
        const t = sheet.data[row - 1 + r];
        for (let c = 0; c < values[r].length; c++) t[col - 1 + c] = values[r][c];
      }
    },
    setValue(v) { while (sheet.data.length < row) sheet.data.push([]); sheet.data[row - 1][col - 1] = v; },
    setFontWeight() { return this; },
    getDataValidation() { return null; },
    clearContent() { const r = sheet.data[row - 1]; if (r) r[col - 1] = ''; },
    sort() { return this; }
  };
}
function makeSheet(name) {
  return {
    name, data: [],
    appendRow(rowArr) { this.data.push(rowArr.slice()); },
    getRange(row, col, numRows, numCols) { return makeRange(this, row, col, numRows || 1, numCols || 1); },
    getLastRow() { return this.data.length; },
    getLastColumn() { return this.data.length ? this.data[0].length : 0; },
    deleteRow(r) { this.data.splice(r - 1, 1); },
    deleteRows(r, n) { this.data.splice(r - 1, n); },
    getDataRange() { return makeRange(this, 1, 1, this.data.length, this.data.length ? this.data[0].length : 0); }
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
  SpreadsheetApp: {
    getActiveSpreadsheet() { return ss; },
    flush() {},
    DataValidationCriteria: { VALUE_IN_LIST: 'VALUE_IN_LIST', VALUE_IN_RANGE: 'VALUE_IN_RANGE' }
  },
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
  ScriptApp: {
    getProjectTriggers() { return []; },
    newTrigger(h) { return { timeBased() { return this; }, everyDays() { return this; }, atHour() { return this; }, create() { return { getHandlerFunction() { return h; } }; } }; },
    deleteTrigger() {}
  },
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

// Lưu ý vm: top-level `const` trong script chạy qua runInContext KHÔNG gắn vào object sandbox
// (khác với `function`/`var`), nên phải đọc qua 1 lệnh runInContext riêng trong CÙNG context.
const actionSecurityGroup = vm.runInContext('ACTION_SECURITY_GROUP_', ctx);

let pass = 0, fail = 0;
function check(name, fn) {
  try { fn(); console.log('PASS -', name); pass++; }
  catch (e) { console.log('FAIL -', name, '=>', e.message); fail++; }
}

function makeEvent(body) { return { postData: { contents: JSON.stringify(body) } }; }
function callDoPost(body) { const res = ctx.doPost(makeEvent(body)); return JSON.parse(res.getContent()); }

function resetSheets() {
  Object.keys(ss.sheets).forEach(k => delete ss.sheets[k]);
  const nhap = ss.insertSheet('VBQPPL_Nhap');
  nhap.appendRow(['Lĩnh vực', 'Mức độ tác động', 'Loại văn bản', 'Tên văn bản', 'Số hiệu', 'Link Văn bản', 'Bộ phận chủ trì', 'Trạng thái duyệt', 'Trạng thái xử lý', 'Ngày chuyển trạng thái']);
  nhap.appendRow(['LV1', 'Cao', 'Thông tư', 'Văn bản test', '99/2026/TT-BNV', 'http://x', 'BP1', '', '', '']);
  const vbqppl = ss.insertSheet('VBQPPL');
  vbqppl.appendRow(['ID VĂN BẢN', 'Lĩnh vực', 'Mức độ tác động', 'Loại văn bản', 'Tên văn bản', 'Số hiệu', 'Link Văn bản', 'Bộ phận chủ trì', 'Trạng thái duyệt', 'Trạng thái xử lý', 'Ngày chuyển trạng thái']);
  vbqppl.appendRow(['ID001', 'LV1', 'Cao', 'Thông tư', 'Văn bản gốc', '01/2020/TT-BNV', 'http://z', 'BP1', '', '', '']);
}

const PUBLIC_TOKEN = 'public-frontend-token';
const SERVICE_TOKEN = 'real-service-token';

function setupScriptProperties() {
  Object.keys(scriptProps).forEach(k => delete scriptProps[k]);
  ctx.setupWebAppToken(PUBLIC_TOKEN);
  scriptProps.APPS_SCRIPT_SERVICE_TOKEN = SERVICE_TOKEN;
  scriptProps.ADMIN_SESSION_SECRET = 'admin-session-secret-test';
  scriptProps.ADMIN_SESSION_TTL_SECONDS = '900';
  const salt = crypto.randomBytes(16);
  const hash = crypto.pbkdf2Sync('P0AdminPass!', salt, 1000, 32, 'sha256');
  scriptProps.ADMIN_PASSWORD_SALT = salt.toString('hex');
  scriptProps.ADMIN_PASSWORD_HASH = hash.toString('hex');
  scriptProps.ADMIN_PASSWORD_ITERATIONS = '1000';
  scriptProps.PLANNER_SYNC_SHARED_SECRET = 'planner-secret-test';
}

// ============================================================
// 0. Không còn fallback legacy trong validateServiceToken_ (Security.js trực tiếp)
// ============================================================
check('validateServiceToken_: PUBLIC_TOKEN đúng (legacy) nhưng service_token sai -> LUÔN throw (không còn fallback)', () => {
  resetSheets(); setupScriptProperties();
  let threw = false, code = '';
  try {
    ctx.validateServiceToken_('wrong-service-token', PUBLIC_TOKEN); // token công khai ĐÚNG nhưng KHÔNG được chấp nhận
  } catch (e) { threw = true; code = e.name; }
  assert.strictEqual(threw, true, 'validateServiceToken_ phải throw khi service_token sai, KỂ CẢ khi legacy token đúng');
  assert.strictEqual(code, 'SERVICE_TOKEN_INVALID');
});

check('validateServiceToken_: KHÔNG gửi service_token, chỉ gửi legacy token đúng -> vẫn throw', () => {
  resetSheets(); setupScriptProperties();
  let threw = false;
  try { ctx.validateServiceToken_('', PUBLIC_TOKEN); } catch (e) { threw = true; }
  assert.strictEqual(threw, true, 'Không được có đường nào cho phép chỉ dùng token công khai để qua service token check');
});

check('validateServiceToken_: service_token đúng -> pass (không phụ thuộc legacy token)', () => {
  resetSheets(); setupScriptProperties();
  const result = ctx.validateServiceToken_(SERVICE_TOKEN, 'bat-ky-gia-tri-nao-cung-duoc');
  assert.strictEqual(result.ok, true);
  assert.strictEqual(result.mode, 'service_token');
});

// ============================================================
// 1-2. import_vbqppl_nhap / update_vbqppl_record (nhóm B) — chỉ token công khai -> bị từ chối
// ============================================================
['import_vbqppl_nhap', 'update_vbqppl_record'].forEach((action) => {
  check(`doPost('${action}') CHỈ có token công khai (không service_token) -> SERVICE_TOKEN_INVALID`, () => {
    resetSheets(); setupScriptProperties();
    const res = callDoPost({ token: PUBLIC_TOKEN, action, payload: { row_number: 2, 'Số hiệu': '01/2020/TT-BNV' } });
    assert.strictEqual(res.ok, false);
    assert.strictEqual(res.error, 'SERVICE_TOKEN_INVALID');
  });

  check(`doPost('${action}') có service_token đúng -> được xử lý (không bị chặn ở tầng xác thực)`, () => {
    resetSheets(); setupScriptProperties();
    const res = callDoPost({ token: PUBLIC_TOKEN, service_token: SERVICE_TOKEN, action, payload: { row_number: 2, 'Số hiệu': '01/2020/TT-BNV', 'Tên văn bản': 'X', 'Loại văn bản': 'Thông tư', 'Link Văn bản': 'http://y' } });
    assert.notStrictEqual(res.error, 'SERVICE_TOKEN_INVALID', 'Không được bị chặn ở lớp xác thực khi có service_token đúng: ' + JSON.stringify(res));
  });
});

// ============================================================
// 3. request_planner_sync_envelope (nhóm C) — chỉ token công khai -> bị từ chối
// ============================================================
check("doPost('request_planner_sync_envelope') CHỈ có token công khai (không admin_session) -> ADMIN_SESSION_REQUIRED", () => {
  resetSheets(); setupScriptProperties();
  const res = callDoPost({ token: PUBLIC_TOKEN, action: 'request_planner_sync_envelope', payload: { path: '/sync-webapp-to-planner', envelope_payload: {} } });
  assert.strictEqual(res.ok, false);
  assert.strictEqual(res.error, 'ADMIN_SESSION_REQUIRED');
});

check("doPost('request_planner_sync_envelope') gửi service_token thay vì admin_session -> VẪN bị từ chối (2 cơ chế độc lập)", () => {
  resetSheets(); setupScriptProperties();
  const res = callDoPost({ token: PUBLIC_TOKEN, service_token: SERVICE_TOKEN, action: 'request_planner_sync_envelope', payload: { path: '/sync-webapp-to-planner', envelope_payload: {} } });
  assert.strictEqual(res.ok, false);
  assert.strictEqual(res.error, 'ADMIN_SESSION_REQUIRED', 'service_token không được phép thay thế admin_session cho action nhóm C');
});

// ============================================================
// 4. Toàn bộ action nhóm B/C khai báo trong ACTION_SECURITY_GROUP_ — quét tự động, không cherry-pick
// ============================================================
check('Mọi action nhóm B trong ACTION_SECURITY_GROUP_ đều từ chối khi chỉ có token công khai', () => {
  resetSheets(); setupScriptProperties();
  const groupBActions = Object.keys(actionSecurityGroup).filter(a => actionSecurityGroup[a] === 'B');
  assert.ok(groupBActions.length > 0, 'Phải có ít nhất 1 action nhóm B để test có ý nghĩa');
  groupBActions.forEach((action) => {
    const res = callDoPost({ token: PUBLIC_TOKEN, action, payload: {} });
    assert.strictEqual(res.ok, false, `Action nhóm B "${action}" phải bị từ chối khi chỉ có token công khai`);
    assert.strictEqual(res.error, 'SERVICE_TOKEN_INVALID', `Action "${action}" trả sai error code: ${res.error}`);
  });
});

check('Mọi action nhóm C trong ACTION_SECURITY_GROUP_ đều từ chối khi chỉ có token công khai', () => {
  resetSheets(); setupScriptProperties();
  const groupCActions = Object.keys(actionSecurityGroup).filter(a => actionSecurityGroup[a] === 'C');
  assert.ok(groupCActions.length > 0, 'Phải có ít nhất 1 action nhóm C để test có ý nghĩa');
  groupCActions.forEach((action) => {
    const res = callDoPost({ token: PUBLIC_TOKEN, action, payload: { path: '/sync-webapp-to-planner', envelope_payload: {} } });
    assert.strictEqual(res.ok, false, `Action nhóm C "${action}" phải bị từ chối khi chỉ có token công khai`);
    assert.strictEqual(res.error, 'ADMIN_SESSION_REQUIRED', `Action "${action}" trả sai error code: ${res.error}`);
  });
});

// ============================================================
// 5. Repair/maintenance KHÔNG lộ qua doPost dù dùng token gì
// ============================================================
['installWebAppDebugLogMaintenanceTrigger', 'removeWebAppDebugLogMaintenanceTrigger', 'executeWebAppDebugLogMaintenance_', 'cleanupIrrelevantRowsAfter90Days', 'createDailyIrrelevantCleanupTrigger'].forEach((action) => {
  check(`doPost('${action}') (hàm bảo trì) -> ACTION_NOT_SUPPORTED dù dùng token công khai`, () => {
    resetSheets(); setupScriptProperties();
    const res = callDoPost({ token: PUBLIC_TOKEN, action, payload: {} });
    assert.strictEqual(res.ok, false);
    assert.strictEqual(res.error, 'ACTION_NOT_SUPPORTED', `"${action}" không được lộ qua doPost dưới bất kỳ hình thức nào`);
  });

  check(`doPost('${action}') -> ACTION_NOT_SUPPORTED dù dùng service_token`, () => {
    resetSheets(); setupScriptProperties();
    const res = callDoPost({ token: PUBLIC_TOKEN, service_token: SERVICE_TOKEN, action, payload: {} });
    assert.strictEqual(res.error, 'ACTION_NOT_SUPPORTED');
  });
});

// ============================================================
// 6. Public-read (nhóm A) vẫn hoạt động CHỈ VỚI token công khai — không bị siết quá tay
// ============================================================
check('Action nhóm A (get_pending_records) chỉ cần token công khai vẫn hoạt động bình thường', () => {
  resetSheets(); setupScriptProperties();
  const res = callDoPost({ token: PUBLIC_TOKEN, action: 'get_pending_records', payload: {} });
  assert.strictEqual(res.ok, true, 'Action đọc công khai không được yêu cầu service_token/admin_session');
});

// ============================================================
// 7. Admin/write action (nhóm C) tuyệt đối không chấp nhận service_token thay cho admin_session
// ============================================================
check("doPost('transfer_record') có service_token hợp lệ nhưng KHÔNG có admin_session -> vẫn bị từ chối", () => {
  resetSheets(); setupScriptProperties();
  const res = callDoPost({ token: PUBLIC_TOKEN, service_token: SERVICE_TOKEN, action: 'transfer_record', payload: { row_number: 2 } });
  assert.strictEqual(res.ok, false);
  assert.strictEqual(res.error, 'ADMIN_SESSION_REQUIRED');
});

check("doPost('transfer_record') có admin_session hợp lệ (đăng nhập thật) -> thành công", () => {
  resetSheets(); setupScriptProperties();
  const login = callDoPost({ token: PUBLIC_TOKEN, action: 'verify_admin', payload: { password: 'P0AdminPass!' } });
  assert.strictEqual(login.ok, true, JSON.stringify(login));
  const res = callDoPost({ token: PUBLIC_TOKEN, admin_session: login.adminSession, action: 'transfer_record', payload: { row_number: 2 } });
  assert.strictEqual(res.ok, true, JSON.stringify(res));
});

console.log('\n----------------------------------------');
console.log(`TOTAL: ${pass + fail}, PASS: ${pass}, FAIL: ${fail}`);
process.exit(fail > 0 ? 1 : 0);
