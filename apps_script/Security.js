/*******************************************************
 * SECURITY.JS — P0 hardening: xác thực, session admin, redact log, signed envelope
 * cho Planner Sync Server. Không có token/password mặc định — mọi secret đọc từ
 * Script Properties (Project Settings → Script Properties trên Apps Script Editor).
 *
 * QUAN TRỌNG (hiệu năng): Apps Script KHÔNG có PBKDF2 dựng sẵn, nên verifyAdminPassword_
 * cài đặt PBKDF2-HMAC-SHA256 thủ công bằng cách lặp Utilities.computeHmacSha256Signature.
 * Với ADMIN_PASSWORD_ITERATIONS mặc định 210000, thao tác này có thể mất vài giây đến
 * hàng chục giây tùy tải hệ thống Google — CHẬM HƠN NHIỀU so với PBKDF2 native trong Python.
 * Nếu đăng nhập admin bị timeout/chậm quá mức chấp nhận được, giảm ADMIN_PASSWORD_ITERATIONS
 * (Script Property, không cần sửa code) — xem SECURITY.md mục "Hiệu năng PBKDF2 trên Apps Script".
 *******************************************************/

// ===== Script Properties helpers =====

function getRequiredScriptProperty_(key) {
  const value = PropertiesService.getScriptProperties().getProperty(key);
  if (!value) {
    throw new SecurityConfigError_('MISSING_SCRIPT_PROPERTY', 'Thiếu Script Property bắt buộc: ' + key);
  }
  return value;
}

function getOptionalScriptProperty_(key, defaultValue) {
  const value = PropertiesService.getScriptProperties().getProperty(key);
  return (value === null || value === undefined || value === '') ? (defaultValue !== undefined ? defaultValue : '') : value;
}

// ===== Lỗi bảo mật có mã ổn định (dùng làm error code trả về client) =====

function SecurityConfigError_(code, message) {
  const err = new Error(message);
  err.name = code || 'SECURITY_CONFIG_ERROR';
  return err;
}

function SecurityAuthError_(code, message) {
  const err = new Error(message);
  err.name = code || 'SECURITY_AUTH_ERROR';
  return err;
}

// ===== Encoding helpers =====

function toUtf8Bytes_(str) {
  return Utilities.newBlob(String(str == null ? '' : str)).getBytes();
}

function toUnsignedBytes_(signedBytes) {
  const out = new Array(signedBytes.length);
  for (let i = 0; i < signedBytes.length; i++) {
    out[i] = signedBytes[i] < 0 ? signedBytes[i] + 256 : signedBytes[i];
  }
  return out;
}

function bytesToHex_(bytes) {
  let hex = '';
  for (let i = 0; i < bytes.length; i++) {
    const b = bytes[i] < 0 ? bytes[i] + 256 : bytes[i];
    hex += (b < 16 ? '0' : '') + b.toString(16);
  }
  return hex;
}

function hexToBytes_(hex) {
  const clean = String(hex || '').trim();
  if (clean.length % 2 !== 0) {
    throw new SecurityConfigError_('INVALID_HEX', 'Chuỗi hex không hợp lệ (độ dài lẻ).');
  }
  const out = [];
  for (let i = 0; i < clean.length; i += 2) {
    out.push(parseInt(clean.substring(i, i + 2), 16));
  }
  return out;
}

function base64UrlEncode_(str) {
  return Utilities.base64EncodeWebSafe(str, Utilities.Charset.UTF_8).replace(/=+$/, '');
}

function base64UrlDecodeToString_(str) {
  let padded = String(str || '');
  const mod = padded.length % 4;
  if (mod === 2) padded += '==';
  else if (mod === 3) padded += '=';
  const bytes = Utilities.base64DecodeWebSafe(padded);
  return Utilities.newBlob(bytes).getDataAsString('UTF-8');
}

// ===== So sánh constant-time (best-effort trong giới hạn của Apps Script) =====

function constantTimeEquals_(a, b) {
  const strA = String(a == null ? '' : a);
  const strB = String(b == null ? '' : b);
  const maxLen = Math.max(strA.length, strB.length);
  let diff = strA.length === strB.length ? 0 : 1;
  for (let i = 0; i < maxLen; i++) {
    const codeA = i < strA.length ? strA.charCodeAt(i) : 0;
    const codeB = i < strB.length ? strB.charCodeAt(i) : 0;
    diff |= (codeA ^ codeB);
  }
  return diff === 0;
}

// ===== HMAC-SHA256 / SHA-256 helpers (hex output) =====

function hmacSha256Hex_(message, secret) {
  const signed = Utilities.computeHmacSha256Signature(String(message), String(secret));
  return bytesToHex_(signed);
}

function hmacSha256Bytes_(keyBytes, messageBytes) {
  const signed = Utilities.computeHmacSha256Signature(messageBytes, keyBytes);
  return toUnsignedBytes_(signed);
}

function sha256Hex_(message) {
  const digest = Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256, String(message));
  return bytesToHex_(digest);
}

// ===== PBKDF2-HMAC-SHA256 (tương thích hashlib.pbkdf2_hmac('sha256', ...) của Python) =====

function pbkdf2HmacSha256_(passwordBytes, saltBytes, iterations, dkLenBytes) {
  const hLen = 32;
  const blockCount = Math.ceil(dkLenBytes / hLen);
  let derived = [];

  for (let blockIndex = 1; blockIndex <= blockCount; blockIndex++) {
    const intBytes = [
      (blockIndex >>> 24) & 0xff, (blockIndex >>> 16) & 0xff,
      (blockIndex >>> 8) & 0xff, blockIndex & 0xff
    ];
    let u = hmacSha256Bytes_(passwordBytes, saltBytes.concat(intBytes));
    const t = u.slice();

    for (let iter = 1; iter < iterations; iter++) {
      u = hmacSha256Bytes_(passwordBytes, u);
      for (let k = 0; k < t.length; k++) {
        t[k] ^= u[k];
      }
    }

    derived = derived.concat(t);
  }

  return derived.slice(0, dkLenBytes);
}

// ===== Service token (action nhóm B — máy-máy: import, sync Planner...) =====

/**
 * Xác thực service token cho action máy-máy (nhóm B). CHỈ chấp nhận APPS_SCRIPT_SERVICE_TOKEN
 * — KHÔNG còn fallback về APPS_SCRIPT_TOKEN (token đó nằm công khai trong Dashboard/index.html,
 * nên không được phép mở khoá action máy-máy/ghi dữ liệu). Script Python phải gửi kèm
 * service_token lấy từ biến môi trường APPS_SCRIPT_SERVICE_TOKEN — xem SECURITY.md.
 * providedLegacyToken không còn được dùng, giữ tham số để không phải sửa mọi call site khi
 * doPost gọi hàm này — nhưng KHÔNG bao giờ được dùng để xác thực.
 */
function validateServiceToken_(providedServiceToken, providedLegacyToken) {
  const configuredServiceToken = getRequiredScriptProperty_('APPS_SCRIPT_SERVICE_TOKEN');

  if (providedServiceToken && constantTimeEquals_(providedServiceToken, configuredServiceToken)) {
    return { ok: true, mode: 'service_token' };
  }

  throw new SecurityAuthError_('SERVICE_TOKEN_INVALID', 'Service token không hợp lệ.');
}

// ===== Admin password (PBKDF2) =====

/**
 * So khớp mật khẩu admin với ADMIN_PASSWORD_HASH (hex) lưu trong Script Properties,
 * dẫn xuất bằng PBKDF2-HMAC-SHA256 với ADMIN_PASSWORD_SALT (hex) + ADMIN_PASSWORD_ITERATIONS.
 * Sinh salt/hash bằng scripts/generate_p0_secrets.py — KHÔNG tự đặt password mặc định.
 */
function verifyAdminPassword_(password) {
  const saltHex = getRequiredScriptProperty_('ADMIN_PASSWORD_SALT');
  const hashHex = getRequiredScriptProperty_('ADMIN_PASSWORD_HASH');
  const iterations = parseInt(getOptionalScriptProperty_('ADMIN_PASSWORD_ITERATIONS', '210000'), 10) || 210000;

  if (!password || !String(password).length) {
    return false;
  }

  const saltBytes = hexToBytes_(saltHex);
  const expectedBytes = hexToBytes_(hashHex);
  const passwordBytes = toUtf8Bytes_(password);
  const derivedBytes = pbkdf2HmacSha256_(passwordBytes, saltBytes, iterations, expectedBytes.length);

  return constantTimeEquals_(bytesToHex_(derivedBytes), bytesToHex_(expectedBytes));
}

// ===== Admin session (ký HMAC, TTL ngắn) =====

const ADMIN_SESSION_VERSION_ = 1;

/**
 * Tạo admin session đã ký HMAC-SHA256. Cấu trúc payload: {v, issuedAt, expiresAt, nonce}.
 * Token trả về dạng "<base64url(payload JSON)>.<hex signature>".
 */
function createAdminSession_() {
  const secret = getRequiredScriptProperty_('ADMIN_SESSION_SECRET');
  const ttlSeconds = parseInt(getOptionalScriptProperty_('ADMIN_SESSION_TTL_SECONDS', '900'), 10) || 900;
  const nowSeconds = Math.floor(new Date().getTime() / 1000);

  const payload = {
    v: ADMIN_SESSION_VERSION_,
    issuedAt: nowSeconds,
    expiresAt: nowSeconds + ttlSeconds,
    nonce: Utilities.getUuid()
  };

  const payloadJson = JSON.stringify(payload);
  const payloadB64 = base64UrlEncode_(payloadJson);
  const signature = hmacSha256Hex_(payloadB64, secret);

  return {
    token: payloadB64 + '.' + signature,
    expiresAt: payload.expiresAt,
    ttlSeconds: ttlSeconds
  };
}

/**
 * Xác minh admin session. Trả về {ok:true, payload} hoặc {ok:false, reason}.
 * Không throw — để caller (requireAdminSession_) quyết định cách báo lỗi.
 */
function validateAdminSession_(sessionToken) {
  if (!sessionToken || typeof sessionToken !== 'string' || sessionToken.indexOf('.') === -1) {
    return { ok: false, reason: 'SESSION_MISSING' };
  }

  const parts = sessionToken.split('.');
  if (parts.length !== 2) {
    return { ok: false, reason: 'SESSION_MALFORMED' };
  }

  const payloadB64 = parts[0];
  const signature = parts[1];

  let secret;
  try {
    secret = getRequiredScriptProperty_('ADMIN_SESSION_SECRET');
  } catch (e) {
    return { ok: false, reason: 'SESSION_SECRET_NOT_CONFIGURED' };
  }

  const expectedSignature = hmacSha256Hex_(payloadB64, secret);
  if (!constantTimeEquals_(signature, expectedSignature)) {
    return { ok: false, reason: 'SESSION_SIGNATURE_INVALID' };
  }

  let payload;
  try {
    payload = JSON.parse(base64UrlDecodeToString_(payloadB64));
  } catch (e) {
    return { ok: false, reason: 'SESSION_PAYLOAD_INVALID' };
  }

  if (!payload || payload.v !== ADMIN_SESSION_VERSION_) {
    return { ok: false, reason: 'SESSION_VERSION_MISMATCH' };
  }

  const nowSeconds = Math.floor(new Date().getTime() / 1000);
  if (!payload.expiresAt || nowSeconds >= payload.expiresAt) {
    return { ok: false, reason: 'SESSION_EXPIRED' };
  }

  return { ok: true, payload: payload };
}

/**
 * Bắt buộc admin session hợp lệ — dùng ở đầu mọi action ghi dữ liệu (nhóm C).
 * Throw SecurityAuthError_ nếu không hợp lệ, để doPost's catch chuẩn hóa response.
 */
function requireAdminSession_(request) {
  const sessionToken = request && (request.admin_session || (request.payload && request.payload.admin_session));
  const result = validateAdminSession_(sessionToken);

  if (!result.ok) {
    throw new SecurityAuthError_('ADMIN_SESSION_REQUIRED', 'Cần đăng nhập quản trị viên hợp lệ để thực hiện thao tác này.');
  }

  return result.payload;
}

// ===== Redact dữ liệu nhạy cảm (dùng chung cho log + response lỗi) =====

const SECURITY_SENSITIVE_KEYS_ = [
  'password', 'token', 'secret', 'session', 'cookie', 'cookies', 'authorization',
  'signature', 'access_token', 'refresh_token', 'client_secret', 'device_code', 'user_code',
  'admin_session', 'adminsessiontoken'
];

function isSecuritySensitiveKey_(key) {
  return SECURITY_SENSITIVE_KEYS_.indexOf(String(key || '').trim().toLowerCase()) !== -1;
}

function redactSensitiveData_(data, depth) {
  const currentDepth = depth || 0;
  if (currentDepth > 20) return '[MAX_DEPTH_REACHED]';

  if (Array.isArray(data)) {
    return data.map(function(item) { return redactSensitiveData_(item, currentDepth + 1); });
  }

  if (data instanceof Date) return data;

  if (data && typeof data === 'object') {
    const out = {};
    Object.keys(data).forEach(function(key) {
      out[key] = isSecuritySensitiveKey_(key) ? '[REDACTED]' : redactSensitiveData_(data[key], currentDepth + 1);
    });
    return out;
  }

  return data;
}

// ===== Sanitize lỗi trả về client (không bao giờ lộ stack trace) =====

const KNOWN_CLIENT_SAFE_ERROR_CODES_ = {
  MISSING_SCRIPT_PROPERTY: true,
  SERVICE_TOKEN_INVALID: true,
  ADMIN_SESSION_REQUIRED: true,
  SESSION_EXPIRED: true,
  ACTION_NOT_SUPPORTED: true,
  INVALID_REQUEST: true
};

function sanitizeErrorForClient_(err, correlationId) {
  const rawName = (err && err.name) ? String(err.name) : 'ERROR';
  const code = KNOWN_CLIENT_SAFE_ERROR_CODES_[rawName] ? rawName : (rawName === 'Error' ? 'INTERNAL_ERROR' : rawName);
  const rawMessage = (err && err.message) ? String(err.message) : 'Đã xảy ra lỗi không xác định.';

  return {
    ok: false,
    error: code,
    message: rawMessage,
    correlationId: correlationId || ''
  };
}

function generateCorrelationId_() {
  return Utilities.getUuid();
}

// ===== Signed envelope cho Planner Sync Server (P0 mục XIV) =====

// Chỉ những path này được phép ký envelope — không ký payload/path tùy ý.
const PLANNER_SYNC_ENVELOPE_ALLOWED_PATHS_ = ['/sync-webapp-to-planner', '/delete-planner-task'];
const PLANNER_SYNC_ENVELOPE_DEFAULT_TTL_SECONDS_ = 60;

/**
 * Tạo signed envelope để frontend chuyển tiếp tới Planner Sync Server cục bộ, KHÔNG bao
 * giờ để lộ PLANNER_SYNC_SHARED_SECRET cho frontend. Envelope gồm body (chuỗi JSON chính
 * xác cần POST nguyên văn), timestamp, requestId, path, signature — ký theo canonical
 * message: timestamp + "\n" + requestId + "\n" + path + "\n" + sha256(body).
 * path phải nằm trong whitelist; payload phải là object thuần (không lồng hàm/undefined).
 */
function createPlannerSyncEnvelope_(path, payload, ttlSeconds) {
  if (PLANNER_SYNC_ENVELOPE_ALLOWED_PATHS_.indexOf(path) === -1) {
    throw new SecurityAuthError_('INVALID_REQUEST', 'Path không nằm trong whitelist ký envelope: ' + path);
  }

  const secret = getRequiredScriptProperty_('PLANNER_SYNC_SHARED_SECRET');
  const ttl = ttlSeconds || PLANNER_SYNC_ENVELOPE_DEFAULT_TTL_SECONDS_;
  const nowSeconds = Math.floor(new Date().getTime() / 1000);

  const bodyString = JSON.stringify(payload || {});
  const bodyHash = sha256Hex_(bodyString);
  const requestId = Utilities.getUuid();
  const timestamp = String(nowSeconds);

  const canonicalMessage = timestamp + '\n' + requestId + '\n' + path + '\n' + bodyHash;
  const signature = hmacSha256Hex_(canonicalMessage, secret);

  return {
    body: bodyString,
    path: path,
    timestamp: timestamp,
    requestId: requestId,
    signature: signature,
    expiresAt: nowSeconds + ttl
  };
}
