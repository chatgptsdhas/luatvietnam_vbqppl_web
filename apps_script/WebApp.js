/*******************************************************
 * WEB APP IMPORT VBQPPL_NHAP (FULL MERGED) + DASHBOARD API
 * - Hỗ trợ options.relationship_value_mode: so_hieu | id_van_ban
 * - Tích hợp API duyệt văn bản: get_pending_records, transfer_record, update_record
 * - Tích hợp API quản lý luồng phụ: get_irrelevant_records, get_expired_records
 *******************************************************/
// test from VS Code/
const WEBAPP_CONFIG = {
  SHEET_VBQPPL: 'VBQPPL',
  SHEET_NHAP: 'VBQPPL_Nhap',
  SHEET_LOG: 'WEBAPP_DEBUG_LOG',
  COL_ID: 'ID VĂN BẢN',
  COL_SO_HIEU: 'Số hiệu',
  TOKEN_PROPERTY_NAME: 'APPS_SCRIPT_TOKEN',
  MAX_LOG_JSON_LEN: 20000, 
  REQUIRED_FOR_TRANSFER: ['Lĩnh vực', 'Mức độ tác động', 'Loại văn bản', 'Tên văn bản', 'Số hiệu', 'Link Văn bản', 'Bộ phận chủ trì']
};

const MANUAL_PROTECTED_COLUMNS = [
  'ID VĂN BẢN', 'Lĩnh vực', 'Chủ đề', 'Mục',
  'Mức độ tác động', 'Bộ phận chủ trì', 'Trạng thái duyệt'
];
const STATUS_KHONG_LIEN_QUAN = 'Không liên quan';
const STATUS_CHO_KIEM_TRA = 'Chờ kiểm tra';
const COL_TRANG_THAI_DUYET = 'Trạng thái duyệt';
const COL_NGAY_CHUYEN_TRANG_THAI = 'Ngày chuyển trạng thái';
const IRRELEVANT_RETENTION_DAYS = 90;
/** =========================
 * SECURITY / TOKEN 
 * ========================= */
function setupWebAppToken(tokenInput) {
  // P0: KHÔNG còn token mặc định — phải truyền token thật (sinh bằng scripts/generate_p0_secrets.py).
  const token = String(tokenInput || '').trim();
  if (!token) throw new Error('Token rỗng. Hãy truyền token vào setupWebAppToken(token) — không còn giá trị mặc định vì lý do bảo mật, xem SECURITY.md.');
  PropertiesService.getScriptProperties().setProperty(WEBAPP_CONFIG.TOKEN_PROPERTY_NAME, token);
  return { ok: true, message: 'Đã lưu token vào Script Properties.' };
}

function clearWebAppToken() {
  PropertiesService.getScriptProperties().deleteProperty(WEBAPP_CONFIG.TOKEN_PROPERTY_NAME);
  return { ok: true, message: 'Đã xoá token.' };
}

function validateToken_(inputToken) {
  const savedToken = PropertiesService.getScriptProperties().getProperty(WEBAPP_CONFIG.TOKEN_PROPERTY_NAME);
  if (!savedToken) throw new Error('Apps Script chưa thiết lập APPS_SCRIPT_TOKEN.');
  if (!inputToken || inputToken !== savedToken) throw new Error('Token không hợp lệ.');
}

/** =========================
 * LOGGING
 * ========================= */

// Correlation ID của request hiện tại (đặt bởi doPost) — jsonResponse_ và appendDebugLog_
// dùng chung để mọi response/log của cùng 1 request có thể truy vết bằng cùng 1 ID.
let CURRENT_CORRELATION_ID_ = '';

/**
 * P0: mọi dữ liệu ghi log đều được redact qua Security.redactSensitiveData_ trước khi
 * stringify (không ghi password/token/session/secret...), và lỗi ghi log không bao giờ
 * làm hỏng request nghiệp vụ đang xử lý.
 */
function appendDebugLog_(stage, data) {
  try {
    const ss = SpreadsheetApp.getActiveSpreadsheet();
    let sheet = ss.getSheetByName(WEBAPP_CONFIG.SHEET_LOG);
    if (!sheet) {
      sheet = ss.insertSheet(WEBAPP_CONFIG.SHEET_LOG);
      sheet.appendRow(['Thời gian', 'Stage', 'Số hiệu', 'Tên văn bản', 'Loại văn bản', 'Data JSON']);
    }

    const rawData = data || {};
    const payload = rawData.payload || {};
    const timeText = Utilities.formatDate(new Date(), Session.getScriptTimeZone(), 'dd/MM/yyyy HH:mm:ss');

    const dataWithCorrelation = Object.assign({}, rawData);
    if (CURRENT_CORRELATION_ID_ && dataWithCorrelation.correlationId === undefined) {
      dataWithCorrelation.correlationId = CURRENT_CORRELATION_ID_;
    }
    const sanitized = redactSensitiveData_(dataWithCorrelation);

    let jsonText = JSON.stringify(sanitized, null, 2) || '{}';
    if (jsonText.length > WEBAPP_CONFIG.MAX_LOG_JSON_LEN) {
      jsonText = jsonText.substring(0, WEBAPP_CONFIG.MAX_LOG_JSON_LEN) + '\n...<trimmed_to_prevent_error>';
    }

    sheet.appendRow([
      timeText, String(stage || ''), payload['Số hiệu'] || '',
      payload['Tên văn bản'] || '', payload['Loại văn bản'] || '', jsonText
    ]);
  } catch (logErr) {
    // Không log lại lỗi này qua appendDebugLog_ (tránh vòng lặp) và không để lỗi ghi log
    // làm hỏng request nghiệp vụ đang xử lý.
    try { Logger.log('appendDebugLog_ failed: ' + (logErr && logErr.message ? logErr.message : logErr)); } catch (ignored) {}
  }
}

// Phân loại action theo P0 security hardening (xem SECURITY.md):
//  A. Public read  — chỉ đọc, không đổi Sheet/Planner/config. Chỉ cần token dự án (validateToken_).
//  B. Service      — action máy-máy (Python pipeline / Planner sync). Cần service token
//                    (validateServiceToken_ — CHỈ chấp nhận APPS_SCRIPT_SERVICE_TOKEN, không còn
//                    fallback về token dự án công khai APPS_SCRIPT_TOKEN).
//  C. Admin/write  — mọi action làm thay đổi dữ liệu từ Dashboard. Bắt buộc admin session hợp lệ
//                    (requireAdminSession_) — KHÔNG dựa vào việc frontend ẩn nút.
const ACTION_SECURITY_GROUP_ = {
  // A. Public read actions
  get_pending_records: 'A',
  get_irrelevant_records: 'A',
  get_expired_records: 'A',
  get_transferred_records: 'A',
  get_all_records: 'A',

  // B. Service actions (máy-máy)
  import_vbqppl_nhap: 'B',
  update_vbqppl_record: 'B',

  // C. Admin/write actions (từ Dashboard, cần đăng nhập quản trị viên)
  transfer_record: 'C',
  update_record: 'C',
  request_planner_sync_envelope: 'C'

  // verify_admin không nằm trong bảng này — đây là action ĐĂNG NHẬP, tự xử lý riêng.
};

// P0 mục XIV: schema whitelist cho từng path Planner Sync Server được phép ký envelope —
// không ký payload tùy ý, chỉ giữ lại đúng các field đã khai báo cho path tương ứng.
const PLANNER_SYNC_PAYLOAD_SCHEMAS_ = {
  '/sync-webapp-to-planner': ['source', 'source_row_number', 'vbqppl_row_number', 'so_hieu', 'limit', 'dry_run'],
  '/delete-planner-task': ['planner_task_id', 'task_id', 'so_hieu', 'ten_van_ban']
};

function sanitizePlannerSyncEnvelopePayload_(path, rawPayload) {
  const allowedKeys = PLANNER_SYNC_PAYLOAD_SCHEMAS_[path];
  if (!allowedKeys) {
    throw new SecurityAuthError_('INVALID_REQUEST', 'Path không được hỗ trợ ký envelope: ' + path);
  }
  const clean = {};
  allowedKeys.forEach(function(key) {
    if (rawPayload && Object.prototype.hasOwnProperty.call(rawPayload, key)) {
      clean[key] = rawPayload[key];
    }
  });
  return clean;
}

/**
 * TRUNG TÂM XỬ LÝ REQUEST TỪ WEBAPP
 */
function doPost(e) {
  CURRENT_CORRELATION_ID_ = generateCorrelationId_();

  try {
    const request = parseRequest_(e);
    appendDebugLog_('REQUEST_RECEIVED', {
      payload: request.payload || {}, options: request.options || {}, action: request.action,
      luoc_do_keys: Object.keys(((request.luoc_do_data || {}).quan_he_phap_ly_theo_luoc_do || {})),
      luoc_do_data: request.luoc_do_data || {}
    });

    validateToken_(request.token);

    // P0: bắt buộc service token / admin session theo nhóm action — không dựa vào frontend ẩn nút.
    const securityGroup = ACTION_SECURITY_GROUP_[request.action];
    if (securityGroup === 'B') {
      validateServiceToken_(request.service_token, request.token);
    } else if (securityGroup === 'C') {
      requireAdminSession_(request);
    }

    // PHÂN LUỒNG XỬ LÝ API
    switch (request.action) {

      // Luồng 1: Giữ nguyên logic Import cũ từ file Python
      case 'import_vbqppl_nhap': {
        const payload = request.payload || {};
        const luocDoData = request.luoc_do_data || {};
        const options = request.options || {};
        const result = processPayload_(payload, luocDoData, options);
        appendDebugLog_('RESULT_CREATED', { payload: payload, write_result: result.write_result || {}, match_report: result.match_report || {}, matched_payload: result.matched_payload || {} });
        return jsonResponse_({ ok: true, message: 'Đã đối chiếu và ghi VBQPPL_Nhap.', result: result });
      }

      // Luồng 2: Lấy danh sách văn bản chờ duyệt cho Dashboard
      case 'get_pending_records': {
        const result = apiGetPendingRecords_();
        return jsonResponse_({
          ok: true,
          data: result.data,
          total: result.total,
          transferred: result.transferred,
          irrelevant: result.irrelevant,
          pending: result.pending
        });
      }

      // Luồng 3: Thực hiện chuyển văn bản khi bấm nút trên Dashboard (nhóm C — cần admin session)
      case 'transfer_record': {
        const transferResult = apiTransferRecord_(request.payload);
        return jsonResponse_(transferResult);
      }

      // Luồng 4: Cập nhật thông tin (Nút Sửa và Nút Bỏ qua) (nhóm C — cần admin session)
      case 'update_record': {
        const updateResult = apiUpdateRecord_(request.payload);
        appendDebugLog_('SUCCESS', { action: 'update_record', result: updateResult });
        return jsonResponse_(updateResult);
      }

      // Luồng 4b: Cập nhật thông tin Planner vào sheet VBQPPL chính (nhóm B — service, gọi từ Python)
      case 'update_vbqppl_record': {
        const updateResult = apiUpdateRecord_(request.payload, WEBAPP_CONFIG.SHEET_VBQPPL);
        appendDebugLog_('SUCCESS', { action: 'update_vbqppl_record', result: updateResult });
        return jsonResponse_(updateResult);
      }

      // Luồng 5: Lấy danh sách văn bản Không liên quan
      case 'get_irrelevant_records': {
        const irrelevantData = apiGetIrrelevantRecords_();
        return jsonResponse_({ ok: true, data: irrelevantData });
      }

      // Luồng 6: Lấy danh sách văn bản Hết hiệu lực
      case 'get_expired_records': {
        const expiredData = apiGetExpiredRecords_();
        return jsonResponse_({ ok: true, data: expiredData });
      }
      // Luồng 7: Lấy danh sách văn bản Đã chuyển (từ sheet VBQPPL_Nhap)
      case 'get_transferred_records': {
        const transferredResult = apiGetTransferredRecords_();
        return jsonResponse_({ ok: true, data: transferredResult, total: transferredResult.length });
      }

      // Bổ sung case này vào danh sách các action trong hàm doPost
      case 'get_all_records': {
        const allData = apiGetAllRecords_();
        return jsonResponse_({ ok: true, data: allData });
      }

      // Luồng kiểm tra bảo mật đăng nhập — P0: PBKDF2 qua Security.js + signed session, không còn
      // mật khẩu plaintext, không còn sessionToken kiểu "AUTHORIZED_<timestamp>" đoán được.
      case 'verify_admin': {
        const inputPass = (request.payload && request.payload.password) || '';

        if (verifyAdminPassword_(inputPass)) {
          const session = createAdminSession_();
          return jsonResponse_({
            ok: true,
            adminSession: session.token,
            expiresAt: session.expiresAt,
            ttlSeconds: session.ttlSeconds
          });
        }

        // Không trả lý do chi tiết khi sai — tránh lộ thông tin cho kẻ tấn công dò mật khẩu.
        return jsonResponse_({ ok: false, error: 'ADMIN_LOGIN_FAILED', message: 'Sai mật khẩu hoặc tài khoản không hợp lệ.' });
      }

      // P0 mục XIV: Dashboard xin envelope đã ký để tự gọi Planner Sync Server cục bộ —
      // frontend KHÔNG BAO GIỜ biết PLANNER_SYNC_SHARED_SECRET. Nhóm C — cần admin session.
      case 'request_planner_sync_envelope': {
        const payload = request.payload || {};
        const path = String(payload.path || '');
        const cleanPayload = sanitizePlannerSyncEnvelopePayload_(path, payload.envelope_payload || {});
        const ttlSeconds = parseInt(getOptionalScriptProperty_('PLANNER_SYNC_REQUEST_TTL_SECONDS', '300'), 10) || 300;
        const envelope = createPlannerSyncEnvelope_(path, cleanPayload, ttlSeconds);
        return jsonResponse_({ ok: true, envelope: envelope });
      }
      default: {
        return jsonResponse_({ ok: false, error: 'ACTION_NOT_SUPPORTED', message: 'Action không được hỗ trợ: ' + request.action });
      }
    }
  } catch (err) {
    // Server-side: log đầy đủ (đã redact tự động trong appendDebugLog_). Client: KHÔNG BAO GIỜ
    // trả stack trace — chỉ trả error code ổn định + message an toàn + correlationId.
    appendDebugLog_('ERROR', { payload: {}, error_name: err.name || 'ERROR', error_message: err.message || String(err), stack: err.stack || '' });
    return jsonResponse_(sanitizeErrorForClient_(err, CURRENT_CORRELATION_ID_));
  } finally {
    CURRENT_CORRELATION_ID_ = '';
  }
}

function parseRequest_(e) {
  if (!e || !e.postData || !e.postData.contents) throw new Error('Request không có postData.contents.');
  try { return JSON.parse(e.postData.contents) || {}; } 
  catch (err) { throw new Error('JSON không hợp lệ trong postData.contents.'); }
}


/* =========================================================================================
 * PHẦN API CHO DASHBOARD DUYỆT VĂN BẢN
 * ========================================================================================= */

// Hàm lấy các dòng cần xử lý trên Dashboard
function apiGetPendingRecords_() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheetNhap = ss.getSheetByName(WEBAPP_CONFIG.SHEET_NHAP);

  if (!sheetNhap) {
    throw new Error('Không tìm thấy sheet: ' + WEBAPP_CONFIG.SHEET_NHAP);
  }

  const lastRow = sheetNhap.getLastRow();

  if (lastRow < 2) {
    return {
      data: [],
      total: 0,
      transferred: 0
    };
  }

  const headers = getHeaderInfo_(sheetNhap).headers;
  const values = sheetNhap
    .getRange(2, 1, lastRow - 1, headers.length)
    .getValues();

  const idxTrangThaiXuLy = headers.indexOf('Trạng thái xử lý');
  const idxTrangThaiDuyet = headers.indexOf('Trạng thái duyệt');

  if (idxTrangThaiXuLy < 0) {
    throw new Error('Sheet VBQPPL_Nhap thiếu cột Trạng thái xử lý.');
  }

  if (idxTrangThaiDuyet < 0) {
    throw new Error('Sheet VBQPPL_Nhap thiếu cột Trạng thái duyệt.');
  }

  const pendingData = [];
  let transferredCount = 0;
  let irrelevantCount = 0;

  for (let i = 0; i < values.length; i++) {
    const statusXuLy = String(values[i][idxTrangThaiXuLy] || '').trim();
    const statusDuyet = String(values[i][idxTrangThaiDuyet] || '').trim();

    if (statusXuLy === 'Đã chuyển') {
      transferredCount++;
      continue;
    }

    if (statusDuyet === 'Không liên quan') {
      irrelevantCount++;
      continue;
    }

    const rowObj = {
      _rowNumber: i + 2
    };

    headers.forEach((h, colIdx) => {
      rowObj[h] = values[i][colIdx];
    });

    pendingData.push(rowObj);
  }

  return {
    data: pendingData,
    total: lastRow - 1,
    transferred: transferredCount,
    irrelevant: irrelevantCount,
    pending: pendingData.length
  };
}

// Hàm lấy danh sách văn bản "Hết hiệu lực"
function apiGetExpiredRecords_() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = ss.getSheetByName('VBQPPL_HetHieuLuc');
  if (!sheet) return [];

  const lastRow = sheet.getLastRow();
  if (lastRow < 2) return [];

  const headers = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getValues()[0].map(String);
  const values = sheet.getRange(2, 1, lastRow - 1, headers.length).getValues();
  const results = [];

  for (let i = 0; i < values.length; i++) {
    const rowObj = { _rowNumber: i + 2 }; 
    headers.forEach((h, colIdx) => {
      let val = values[i][colIdx];
      if (val instanceof Date) {
          val = Utilities.formatDate(val, Session.getScriptTimeZone(), "dd/MM/yyyy");
      }
      rowObj[h] = val;
    });
    results.push(rowObj);
  }
  return results;
}

// Hàm xử lý logic chuyển dòng
function apiTransferRecord_(payload) {
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(10000)) return { ok: false, message: 'Hệ thống Google đang bận, vui lòng thử lại sau.' };

  try {
    const rowNum = Number(payload.row_number);
    if (!rowNum || rowNum < 2) throw new Error('row_number không hợp lệ.');

    const ss = SpreadsheetApp.getActiveSpreadsheet();
    const sheetNhap = ss.getSheetByName(WEBAPP_CONFIG.SHEET_NHAP);
    const sheetVbqppl = ss.getSheetByName(WEBAPP_CONFIG.SHEET_VBQPPL);

    const headersNhap = getHeaderInfo_(sheetNhap).headers;
    const rowValues = sheetNhap.getRange(rowNum, 1, 1, headersNhap.length).getValues()[0];
    const rowObj = headersNhap.reduce((acc, h, i) => { acc[h] = rowValues[i]; return acc; }, {});

    // Bước 1. Kiểm tra thiếu trường
    const missing = WEBAPP_CONFIG.REQUIRED_FOR_TRANSFER.filter(k => !String(rowObj[k] || '').trim());
    if (missing.length > 0) {
      updateStatusInRow_(sheetNhap, headersNhap, rowNum, null, 'Cần kiểm tra thủ công');
      SpreadsheetApp.flush();
      return { ok: false, reason: 'missing_fields', missing: missing, message: 'Thiếu các trường bắt buộc.' };
    }

    // Bước 2. Kiểm tra trùng
    const soHieu = String(rowObj['Số hiệu'] || '').trim();
    if (apiIsDuplicateSoHieu_(sheetVbqppl, soHieu)) {
      updateStatusInRow_(sheetNhap, headersNhap, rowNum, null, 'Trùng số hiệu');
      SpreadsheetApp.flush();
      return { ok: false, reason: 'duplicate', message: 'Văn bản này đã tồn tại trong sheet đích.' };
    }

    // Bước 3. Chuyển
    const transferTime = Utilities.formatDate(new Date(), Session.getScriptTimeZone(), "dd/MM/yyyy HH:mm:ss");
    rowObj["Ngày chuyển trạng thái"] = transferTime;
    const headersVbqppl = getHeaderInfo_(sheetVbqppl).headers;
    const newRowData = headersVbqppl.map(h => rowObj[h] !== undefined ? rowObj[h] : '');
    sheetVbqppl.appendRow(newRowData);

    // Bước 4. Cập nhật
    updateStatusInRow_(sheetNhap, headersNhap, rowNum, 'Đã kiểm tra', 'Đã chuyển', transferTime);
    appendDebugLog_('API_TRANSFER_OK', { so_hieu: soHieu, row_number: rowNum });

    // =========================================================================
    // TÍCH HỢP QUÉT VĂN BẢN HẾT HIỆU LỰC (BẮT BUỘC CHẠY)
    // Nếu chưa tạo file Module_HetHieuLuc.gs, code sẽ báo lỗi vào WEBAPP_DEBUG_LOG
    // =========================================================================
    try { 
       scanAndLogExpiredDocs(soHieu, rowObj['Tên văn bản'], rowObj['Link Văn bản']); 
    } catch(e) { 
       appendDebugLog_('EXPIRED_SCAN_ERROR', { error: 'Lỗi chạy scanAndLogExpiredDocs. Đảm bảo file Module_HetHieuLuc.gs đã được tạo. Chi tiết: ' + e.message }); 
    }

    SpreadsheetApp.flush();
    return { ok: true, message: 'Chuyển dữ liệu thành công!', soHieu: soHieu };

  } catch (err) {
    return { ok: false, message: 'Lỗi server: ' + err.message };
  } finally {
    lock.releaseLock();
  }
}
function apiUpdateRecord_(payload, targetSheetName) {
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(10000)) return { ok: false, message: 'Hệ thống bận.' };

  try {
    if (!payload || !Object.prototype.hasOwnProperty.call(payload, 'row_number')) {
      throw new Error('Thiếu row_number trong payload.');
    }

    const rowNum = Number(payload.row_number);
    if (!rowNum || rowNum < 2) throw new Error('row_number không hợp lệ.');

    const ss = SpreadsheetApp.getActiveSpreadsheet();
    const sheetName = String(targetSheetName || WEBAPP_CONFIG.SHEET_NHAP).trim();
    const allowedSheets = [WEBAPP_CONFIG.SHEET_NHAP, WEBAPP_CONFIG.SHEET_VBQPPL];
    if (allowedSheets.indexOf(sheetName) === -1) throw new Error('Sheet update không được hỗ trợ: ' + sheetName);

    const sheet = ss.getSheetByName(sheetName);
    if (!sheet) throw new Error('Không tìm thấy sheet: ' + sheetName);
    if (rowNum > sheet.getLastRow()) throw new Error('row_number không tồn tại trong sheet ' + sheetName + ': ' + rowNum);

    const headerInfo = getHeaderInfo_(sheet);
    const headers = headerInfo.headers;
    
    const updates = payload.updates || {};

    Object.keys(updates).forEach(colName => {
      const colIndex = headers.indexOf(colName);

      if (colIndex >= 0) {
        // Không cho ghi nhầm "Không liên quan" vào Trạng thái xử lý
        if (sheetName === WEBAPP_CONFIG.SHEET_NHAP && colName === 'Trạng thái xử lý' && updates[colName] === STATUS_KHONG_LIEN_QUAN) return;

        sheet.getRange(rowNum, colIndex + 1).setValue(updates[colName]);
      }
    });

    // Đóng dấu ngày khi Dashboard/API đổi Trạng thái duyệt
    if (sheetName === WEBAPP_CONFIG.SHEET_NHAP) {
      stampIrrelevantDateIfNeeded_(sheet, headers, rowNum, updates);
    }

    SpreadsheetApp.flush();

    return { 
      ok: true, 
      message: 'Đã lưu thông tin thành công!',
      row_number: rowNum,
      sheet_name: sheetName
    };

  } catch (err) {
    return { ok: false, message: 'Lỗi đồng bộ Sheet: ' + err.message };
  } finally {
    lock.releaseLock();
  }
}
function stampIrrelevantDateIfNeeded_(sheet, headers, rowNumber, updates) {
  const statusColName = COL_TRANG_THAI_DUYET;
  const dateColName = COL_NGAY_CHUYEN_TRANG_THAI;

  const statusIdx = headers.indexOf(statusColName);
  let dateIdx = headers.indexOf(dateColName);

  if (statusIdx < 0) return;

  // Nếu gọi từ API mà không cập nhật Trạng thái duyệt thì không làm gì
  if (updates && !Object.prototype.hasOwnProperty.call(updates, statusColName)) {
    return;
  }

  // Nếu chưa có cột ngày thì tự tạo ở cuối sheet
  if (dateIdx < 0) {
    dateIdx = headers.length;
    sheet.getRange(1, dateIdx + 1).setValue(dateColName);
    headers.push(dateColName);
  }

  const newStatus = updates && Object.prototype.hasOwnProperty.call(updates, statusColName)
    ? String(updates[statusColName] || '').trim()
    : String(sheet.getRange(rowNumber, statusIdx + 1).getValue() || '').trim();

  const dateCell = sheet.getRange(rowNumber, dateIdx + 1);

  if (newStatus === STATUS_KHONG_LIEN_QUAN) {
    if (!dateCell.getValue()) {
      dateCell.setValue(new Date());
    }
  } else {
    // Nếu khôi phục hoặc đổi sang trạng thái khác thì xóa mốc ngày
    dateCell.clearContent();
  }
}
function apiIsDuplicateSoHieu_(sheetVbqppl, soHieu) {
  if (!soHieu) return false;

  const h = getHeaderInfo_(sheetVbqppl).headers;
  const idx = h.indexOf('Số hiệu');

  if (idx < 0 || sheetVbqppl.getLastRow() < 2) return false;

  const targetRaw = String(soHieu || '').trim();
  const targetNormalized = normalizeDocNumberForMatch_(targetRaw);

  const allSoHieu = sheetVbqppl
    .getRange(2, idx + 1, sheetVbqppl.getLastRow() - 1, 1)
    .getValues()
    .flat();

  return allSoHieu.some(x => {
    const currentRaw = String(x || '').trim();

    if (currentRaw === targetRaw) return true;

    const currentNormalized = normalizeDocNumberForMatch_(currentRaw);

    return currentNormalized && targetNormalized && currentNormalized === targetNormalized;
  });
}

function updateStatusInRow_(sheet, headers, row, duyet, xuly, transferTime) {
  const d = headers.indexOf('Trạng thái duyệt');
  const x = headers.indexOf('Trạng thái xử lý');
  const t = headers.indexOf(COL_NGAY_CHUYEN_TRANG_THAI);
  if (d >= 0 && duyet) sheet.getRange(row, d + 1).setValue(duyet);
  if (x >= 0 && xuly) sheet.getRange(row, x + 1).setValue(xuly);
  if (t >= 0 && transferTime) sheet.getRange(row, t + 1).setValue(transferTime);
}

/* =========================================================================================
 * PHẦN XỬ LÝ IMPORT PYTHON
 * ========================================================================================= */

function processPayload_(payload, luocDoData, options) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheetVbqppl = ss.getSheetByName(WEBAPP_CONFIG.SHEET_VBQPPL);
  const sheetNhap = ss.getSheetByName(WEBAPP_CONFIG.SHEET_NHAP);
  if (!sheetVbqppl) throw new Error('Không tìm thấy sheet: ' + WEBAPP_CONFIG.SHEET_VBQPPL);
  if (!sheetNhap) throw new Error('Không tìm thấy sheet: ' + WEBAPP_CONFIG.SHEET_NHAP);

  const vbqpplIndexInfo = buildVbqpplIndex_(sheetVbqppl);
  const matchResult = matchRelationships_(luocDoData, vbqpplIndexInfo.index);
  const finalPayload = applyMatchResultToPayload_(payload, matchResult, options || {});
  syncReverseGuidanceLinks_(sheetNhap, finalPayload, options || {});

  const skipCheck = shouldSkipPayloadBeforeWrite_(payload);
  if (skipCheck.skip) {
    return { write_result: { action: 'skipped', reason_code: skipCheck.code, reason_message: skipCheck.message, so_hieu: payload['Số hiệu'] || '' } };
  }
  const writeResult = upsertToNhapSheet_(sheetNhap, finalPayload);
  return { write_result: writeResult, matched_payload: finalPayload, match_report: matchResult.report, vbqppl_index_count: vbqpplIndexInfo.count };
}

function parseRelationshipCellValues_(raw) {
  return uniqueList_(String(raw || '').replace(/\r/g, '\n').split(/[\n,;]+/).map(s => String(s || '').trim()).filter(Boolean));
}

function isValueAllowedByValidation_(cell, value) {
  const rule = cell.getDataValidation();
  const v = String(value || '').trim();
  if (!rule || !v) return true;
  const criteriaType = rule.getCriteriaType();
  const args = rule.getCriteriaValues() || [];
  if (criteriaType === SpreadsheetApp.DataValidationCriteria.VALUE_IN_LIST) {
    const allowed = (args[0] || []).map(x => String(x || '').trim());
    return allowed.indexOf(v) !== -1;
  }
  if (criteriaType === SpreadsheetApp.DataValidationCriteria.VALUE_IN_RANGE) {
    const range = args[0];
    if (!range) return true;
    const allowed = range.getDisplayValues().flat().map(x => String(x || '').trim()).filter(Boolean);
    return allowed.indexOf(v) !== -1;
  }
  return true;
}

function safeSetRelationshipValues_(cell, values, options) {
  const normalized = uniqueList_((values || []).map(v => String(v || '').trim()).filter(Boolean));
  const allowed = normalized.filter(v => isValueAllowedByValidation_(cell, v));
  let strategy = String((options && options.relationship_cell_strategy) || 'multi_select').toLowerCase();
  if (strategy === 'first_only') strategy = 'multi_select';
  const nextValue = (strategy === 'multi_line') ? allowed.join('\n') : allowed.join(', ');
  cell.setValue(nextValue);
  return { written: allowed, skipped: normalized.filter(v => allowed.indexOf(v) === -1) };
}

function syncReverseGuidanceLinks_(sheetNhap, finalPayload, options) {
  const currentSoHieu = String(finalPayload['Số hiệu'] || '').trim();
  if (!currentSoHieu) return;
  const canCuValues = parseRelationshipCellValues_(finalPayload['Căn cứ pháp lý'] || '');
  if (!canCuValues.length) return;

  const headerInfo = getHeaderInfo_(sheetNhap);
  const map = headerInfo.map;
  if (!map['Số hiệu'] || !map['Hướng dẫn thực hiện']) return;

  canCuValues.forEach(canCuSoHieu => {
    const rowNum = findRowByValue_(sheetNhap, map['Số hiệu'], canCuSoHieu);
    if (rowNum < 2) return;
    const targetCell = sheetNhap.getRange(rowNum, map['Hướng dẫn thực hiện']);
    const currentCell = targetCell.getValue();
    const values = parseRelationshipCellValues_(currentCell);
    if (values.indexOf(currentSoHieu) !== -1) return;
    values.push(currentSoHieu);
    safeSetRelationshipValues_(targetCell, values, options || {});
  });

  const suaDoiBoSungBoiValues = parseRelationshipCellValues_(finalPayload['Sửa đổi, bổ sung bởi'] || '');
  suaDoiBoSungBoiValues.forEach(soHieuVanBanA => {
    if (!map['Sửa đổi, bổ sung cho']) return;
    const rowNum = findRowByValue_(sheetNhap, map['Số hiệu'], soHieuVanBanA);
    if (rowNum < 2) return;
    const targetCell = sheetNhap.getRange(rowNum, map['Sửa đổi, bổ sung cho']);
    const currentCell = targetCell.getValue();
    const values = parseRelationshipCellValues_(currentCell);
    if (values.indexOf(currentSoHieu) !== -1) return;
    values.push(currentSoHieu);
    safeSetRelationshipValues_(targetCell, values, options || {});
  });
}

function buildVbqpplIndex_(sheet) {
  const values = sheet.getDataRange().getValues();
  if (values.length < 2) throw new Error('Sheet VBQPPL chưa có dữ liệu.');
  const headers = values[0].map(String);
  const idColIndex = headers.indexOf(WEBAPP_CONFIG.COL_ID);
  const soHieuColIndex = headers.indexOf(WEBAPP_CONFIG.COL_SO_HIEU);
  if (idColIndex === -1) throw new Error('Thiếu cột: ' + WEBAPP_CONFIG.COL_ID);
  if (soHieuColIndex === -1) throw new Error('Thiếu cột: ' + WEBAPP_CONFIG.COL_SO_HIEU);

  const index = {};
  for (let r = 1; r < values.length; r++) {
    const idVanBan = String(values[r][idColIndex] || '').trim();
    const soHieu = String(values[r][soHieuColIndex] || '').trim();
    if (!idVanBan || !soHieu) continue;
    const key = normalizeDocNumberForMatch_(soHieu);
    if (!key || index[key]) continue;
    index[key] = { id_van_ban: idVanBan, so_hieu: soHieu, row_number: r + 1 };
  }
  return { index: index, count: Object.keys(index).length };
}

function normalizeDocNumberForMatch_(value) {
  let text = String(value || '').trim();
  if (!text) return '';
  text = text.replace(/Đ/g, 'D').replace(/đ/g, 'd').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toUpperCase();
  return text.replace(/[‐-‒–—−]/g, '-').replace(/\s+/g, '').replace(/-/g, '').replace(/\./g, '');
}

function getPrimaryItemsFromHeading_(relationships, heading) {
  const data = relationships[heading] || {};
  const items = Array.isArray(data.items) ? data.items : [];
  const result = [];
  items.forEach(item => {
    let primaryNumber = String(item.so_hieu_chinh || '').trim();
    if (!primaryNumber) {
      const fallback = Array.isArray(item.so_hieu_tim_duoc) ? item.so_hieu_tim_duoc : [];
      primaryNumber = String(fallback[0] || '').trim();
    }
    if (!primaryNumber) return;
    result.push({ so_hieu_chinh: primaryNumber, noi_dung: String(item.noi_dung || '').trim() });
  });
  return result;
}

function matchRelationships_(luocDoData, vbqpplIndex) {
  const relationships = luocDoData.quan_he_phap_ly_theo_luoc_do || {};
  const allTrackedHeadings = ['Văn bản căn cứ', 'Văn bản được hướng dẫn', 'Văn bản hướng dẫn', 'Văn bản hết hiệu lực', 'Văn bản bị quy định hết hiệu lực', 'Văn bản hết hiệu lực một phần', 'Văn bản được hợp nhất', 'Văn bản bị đình chỉ', 'Văn bản bị đình chỉ một phần', 'Văn bản được đính chính', 'Văn bản thay thế', 'Văn bản quy định hết hiệu lực', 'Văn bản quy định hết hiệu lực một phần', 'Văn bản hợp nhất', 'Văn bản đình chỉ', 'Văn bản đình chỉ một phần', 'Văn bản đính chính', 'Văn bản sửa đổi, bổ sung', 'Văn bản bị sửa đổi, bổ sung'];
  const noteOnlyHeadings = ['Văn bản hướng dẫn', 'Văn bản hết hiệu lực', 'Văn bản bị quy định hết hiệu lực', 'Văn bản hết hiệu lực một phần', 'Văn bản được hợp nhất', 'Văn bản bị đình chỉ', 'Văn bản bị đình chỉ một phần', 'Văn bản được đính chính', 'Văn bản thay thế', 'Văn bản quy định hết hiệu lực', 'Văn bản quy định hết hiệu lực một phần', 'Văn bản hợp nhất', 'Văn bản đình chỉ', 'Văn bản đình chỉ một phần', 'Văn bản đính chính'];
  const rules = [
    { heading: 'Văn bản căn cứ', official_column: 'Căn cứ pháp lý' },
    { heading: 'Văn bản được hướng dẫn', official_column: 'Hướng dẫn thực hiện' },
    { heading: 'Văn bản bị sửa đổi, bổ sung', official_column: 'Sửa đổi, bổ sung cho' },
    { heading: 'Văn bản sửa đổi, bổ sung', official_column: 'Sửa đổi, bổ sung bởi' },
  ];

  const report = {};
  const missingGroups = {};
  rules.forEach(rule => {
    const items = getPrimaryItemsFromHeading_(relationships, rule.heading);
    const matchedIds = [];
    const matchedDetails = [];
    const missingItems = [];
    items.forEach(item => {
      const key = normalizeDocNumberForMatch_(item.so_hieu_chinh);
      if (key && vbqpplIndex[key]) {
        const m = vbqpplIndex[key];
        matchedIds.push(m.id_van_ban);
        matchedDetails.push({ so_hieu_tu_luoc_do: item.so_hieu_chinh, id_van_ban: m.id_van_ban, so_hieu_trong_vbqppl: m.so_hieu, row_number: m.row_number, noi_dung_luoc_do: item.noi_dung });
      } else {
        missingItems.push({ so_hieu_tu_luoc_do: item.so_hieu_chinh, noi_dung_luoc_do: item.noi_dung });
      }
    });
    report[rule.heading] = { official_column: rule.official_column, items_from_luoc_do: items, matched_ids: uniqueList_(matchedIds), matched_details: matchedDetails, missing_items: missingItems };
    if (missingItems.length) missingGroups[rule.heading] = { official_column: rule.official_column, missing_items: missingItems };
  });

  const noteItems = [];
  const allMissingDocNumbers = [];
  noteOnlyHeadings.forEach(heading => {
    const items = getPrimaryItemsFromHeading_(relationships, heading);
    items.forEach(it => { const so = String(it.so_hieu_chinh || '').trim(); if (so) noteItems.push(`${heading} - ${so}`); });
  });
  allTrackedHeadings.forEach(heading => {
    const items = getPrimaryItemsFromHeading_(relationships, heading);
    items.forEach(it => { const so = String(it.so_hieu_chinh || '').trim(); const key = normalizeDocNumberForMatch_(so); if (so && key && !vbqpplIndex[key]) allMissingDocNumbers.push(so); });
  });
  return { report: report, missing_groups: missingGroups, has_missing: Object.keys(missingGroups).length > 0, note_items: uniqueList_(noteItems), missing_doc_numbers: uniqueList_(allMissingDocNumbers) };
}

function resolveRelationshipCellValue_(ids, soHieus, mode, cellStrategy) {
  const values = (mode === 'id_van_ban') ? ids : soHieus;
  const normalized = uniqueList_(values);
  const strategy = String(cellStrategy || 'multi_select').toLowerCase();
  if (strategy === 'multi_line') return normalized.join('\n');
  if (strategy === 'multi_select') return normalized.join(', ');
  return normalized.length ? normalized[0] : '';
}

function normalizeRelationshipStatus_(value) {
  const allowed = ['Chưa quét', 'Đã gợi ý', 'Cần kiểm tra thủ công', 'Cần xác nhận', 'Lỗi quét'];
  const text = String(value || '').trim();
  return (allowed.indexOf(text) !== -1) ? text : 'Đã gợi ý';
}

function applyMatchResultToPayload_(payload, matchResult, options) {
  const finalPayload = Object.assign({}, payload);
  let mode = String((options && options.relationship_value_mode) || 'so_hieu').toLowerCase();
  if (mode !== 'id_van_ban') mode = 'so_hieu';
  let cellStrategy = String((options && options.relationship_cell_strategy) || 'multi_select').toLowerCase();
  if (['first_only', 'multi_line', 'multi_select'].indexOf(cellStrategy) === -1) cellStrategy = 'multi_select';

  Object.keys(matchResult.report).forEach(heading => {
    const item = matchResult.report[heading];
    const ids = item.matched_ids || [];
    const soHieus = (item.matched_details || []).map(d => d.so_hieu_trong_vbqppl || d.so_hieu_tu_luoc_do || '');
    finalPayload[item.official_column] = resolveRelationshipCellValue_(ids, soHieus, mode, cellStrategy);
  });

  finalPayload['Văn bản chưa có trong danh mục'] = (matchResult.missing_doc_numbers || []).join(', ');
  const oldNote = String(finalPayload['Ghi chú quan hệ pháp lý'] || '').trim();
  const extraNote = (matchResult.note_items || []).join('\n');
  finalPayload['Ghi chú quan hệ pháp lý'] = [oldNote, extraNote].filter(Boolean).join('\n');
  finalPayload['Trạng thái quan hệ pháp lý'] = normalizeRelationshipStatus_(finalPayload['Trạng thái quan hệ pháp lý']);
  return finalPayload;
}

function upsertToNhapSheet_(sheet, payload) {
  const headerInfo = getHeaderInfo_(sheet);
  const headers = headerInfo.headers;
  const headerMap = headerInfo.map;
  if (!headerMap['Số hiệu']) throw new Error('Sheet VBQPPL_Nhap thiếu cột Số hiệu.');
  const soHieu = String(payload['Số hiệu'] || '').trim();
  if (!soHieu) throw new Error('Payload thiếu Số hiệu.');

  const targetRow = findRowByValue_(sheet, headerMap['Số hiệu'], soHieu);
  const newRowValues = headers.map(h => (payload[h] !== undefined ? payload[h] : ''));
  if (targetRow > 0) {
    const oldRowValues = sheet.getRange(targetRow, 1, 1, headers.length).getValues()[0];
    const merged = headers.map((h, i) => {
      const oldV = oldRowValues[i], newV = newRowValues[i];
      const protectedCol = MANUAL_PROTECTED_COLUMNS.indexOf(h) !== -1;
      if (protectedCol && String(oldV || '').trim()) return oldV;
      if (protectedCol && !String(newV || '').trim()) return oldV;
      return newV;
    });
    sheet.getRange(targetRow, 1, 1, merged.length).setValues([merged]);
    sheet.getRange(targetRow, 1, 1, merged.length).setFontWeight('normal');
    return { action: 'updated', row_number: targetRow, so_hieu: soHieu };
  }
  sheet.appendRow(newRowValues);
  sheet.getRange(sheet.getLastRow(), 1, 1, headers.length).setFontWeight('normal');
  return { action: 'inserted', row_number: sheet.getLastRow(), so_hieu: soHieu };
}

function getHeaderInfo_(sheet) {
  const lastCol = sheet.getLastColumn();
  if (lastCol < 1) throw new Error('Sheet không có header.');
  const headers = sheet.getRange(1, 1, 1, lastCol).getValues()[0].map(v => String(v || '').trim());
  const map = {};
  headers.forEach((h, i) => { if (h) map[h] = i + 1; });
  return { headers: headers, map: map };
}

function findRowByValue_(sheet, colNumber, value) {
  const lastRow = sheet.getLastRow();
  if (lastRow < 2) return -1;

  const values = sheet.getRange(2, colNumber, lastRow - 1, 1).getValues();
  const targetRaw = String(value || '').trim();

  if (!targetRaw) return -1;

  // 1. Ưu tiên khớp chính xác trước
  for (let i = 0; i < values.length; i++) {
    const currentRaw = String(values[i][0] || '').trim();

    if (currentRaw === targetRaw) {
      return i + 2;
    }
  }

  // 2. Nếu không khớp chính xác, khớp bằng chuẩn hóa số hiệu
  const targetNormalized = normalizeDocNumberForMatch_(targetRaw);

  if (!targetNormalized) return -1;

  for (let i = 0; i < values.length; i++) {
    const currentNormalized = normalizeDocNumberForMatch_(values[i][0]);

    if (currentNormalized && currentNormalized === targetNormalized) {
      return i + 2;
    }
  }

  return -1;
}

function shouldSkipPayloadBeforeWrite_(payload) {
  const allowedTypes = ['Bộ luật', 'Luật', 'Nghị định', 'Thông tư'];
  const skipTypes = ['Chỉ thị', 'Quyết định', 'Văn bản hợp nhất', 'Công văn'];
  const soHieu = String(payload['Số hiệu'] || '').trim();
  const loaiVanBan = String(payload['Loại văn bản'] || '').trim();
  const tenVanBan = String(payload['Tên văn bản'] || '').toLowerCase();
  const linkVanBan = String(payload['Link Văn bản'] || '').toLowerCase();
  if (!soHieu) return { skip: true, code: 'MISSING_SO_HIEU', message: 'Bỏ qua vì thiếu Số hiệu.' };
  if (skipTypes.indexOf(loaiVanBan) !== -1) return { skip: true, code: 'SKIP_DOC_TYPE', message: 'Bỏ qua vì Loại văn bản không dùng: ' + loaiVanBan };
  if (allowedTypes.indexOf(loaiVanBan) === -1) return { skip: true, code: 'DOC_TYPE_NOT_ACCEPTED', message: 'Bỏ qua vì Loại văn bản không thuộc nhóm dùng cho VBQPPL_Nhap: ' + loaiVanBan };
  const excludedKeywords = ['van-ban-hop-nhat', 'văn bản hợp nhất', 'vbhn', 'chi-thi', 'chỉ thị', 'quyet-dinh', 'quyết định', 'cong-van', 'công văn'];
  for (const keyword of excludedKeywords) if (tenVanBan.indexOf(keyword) !== -1 || linkVanBan.indexOf(keyword) !== -1) return { skip: true, code: 'EXCLUDED_KEYWORD', message: 'Bỏ qua vì chứa từ khóa loại trừ: ' + keyword };
  return { skip: false, code: '', message: '' };
}

function jsonResponse_(obj) {
  const body = Object.assign({}, obj);
  if (CURRENT_CORRELATION_ID_ && body.correlationId === undefined) {
    body.correlationId = CURRENT_CORRELATION_ID_;
  }
  return ContentService.createTextOutput(JSON.stringify(body)).setMimeType(ContentService.MimeType.JSON);
}

// Hàm lấy TOÀN BỘ dữ liệu từ Kho VBQPPL chính
function apiGetAllRecords_() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheetVB = ss.getSheetByName(WEBAPP_CONFIG.SHEET_VBQPPL); 
  if (!sheetVB) throw new Error('Không tìm thấy sheet: ' + WEBAPP_CONFIG.SHEET_VBQPPL);

  const lastRow = sheetVB.getLastRow();
  if (lastRow < 2) return [];

  const headers = getHeaderInfo_(sheetVB).headers;
  const values = sheetVB.getRange(2, 1, lastRow - 1, headers.length).getValues();
  
  const allData = [];
  for (let i = 0; i < values.length; i++) {
    const rowObj = { _rowNumber: i + 2 }; 
    headers.forEach((h, colIdx) => { rowObj[h] = values[i][colIdx]; });
    allData.push(rowObj);
  }
  return allData;
}
// Hàm lấy danh sách văn bản "Đã chuyển" từ sheet VBQPPL_Nhap
function apiGetTransferredRecords_() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheetNhap = ss.getSheetByName(WEBAPP_CONFIG.SHEET_NHAP);
  if (!sheetNhap) throw new Error('Không tìm thấy sheet: ' + WEBAPP_CONFIG.SHEET_NHAP);
 
  const lastRow = sheetNhap.getLastRow();
  if (lastRow < 2) return [];
 
  const headers = getHeaderInfo_(sheetNhap).headers;
  const values = sheetNhap.getRange(2, 1, lastRow - 1, headers.length).getValues();
  const idxTrangThaiXuLy = headers.indexOf('Trạng thái xử lý');
 
  if (idxTrangThaiXuLy < 0) {
    throw new Error('Sheet VBQPPL_Nhap thiếu cột Trạng thái xử lý.');
  }
 
  const tz = Session.getScriptTimeZone();
  const result = [];
 
  for (let i = 0; i < values.length; i++) {
    const statusXuLy = String(values[i][idxTrangThaiXuLy] || '').trim();
    if (statusXuLy !== 'Đã chuyển') continue;
 
    const rowObj = { _rowNumber: i + 2 };
    headers.forEach((h, colIdx) => {
      let val = values[i][colIdx];
      if (val instanceof Date) {
        val = Utilities.formatDate(val, tz, 'dd/MM/yyyy');
      }
      rowObj[h] = val;
    });
    result.push(rowObj);
  }
 
  return result;
}
// Hàm lấy danh sách văn bản "Không liên quan"
function apiGetIrrelevantRecords_() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheetNhap = ss.getSheetByName(WEBAPP_CONFIG.SHEET_NHAP);
  if (!sheetNhap) throw new Error('Không tìm thấy sheet: ' + WEBAPP_CONFIG.SHEET_NHAP);

  const lastRow = sheetNhap.getLastRow();
  if (lastRow < 2) return [];

  const headers = getHeaderInfo_(sheetNhap).headers;
  const values = sheetNhap.getRange(2, 1, lastRow - 1, headers.length).getValues();
  const idxTrangThaiDuyet = headers.indexOf('Trạng thái duyệt');
  
  const irrelevantData = [];

  for (let i = 0; i < values.length; i++) {
    const statusDuyet = String(values[i][idxTrangThaiDuyet] || '').trim();
    
    // Chỉ lấy những dòng bị đánh dấu Không liên quan
    if (statusDuyet === 'Không liên quan') {
      const rowObj = { _rowNumber: i + 2 }; 
      headers.forEach((h, colIdx) => { rowObj[h] = values[i][colIdx]; });
      irrelevantData.push(rowObj);
    }
  }

  return irrelevantData;
}
function onEdit(e) {
  if (!e || !e.range) return;

  const sheet = e.range.getSheet();
  if (sheet.getName() !== WEBAPP_CONFIG.SHEET_NHAP) return;

  const row = e.range.getRow();
  if (row <= 1) return;

  const headers = getHeaderInfo_(sheet).headers;
  const statusIdx = headers.indexOf(COL_TRANG_THAI_DUYET);

  if (statusIdx < 0) return;

  // Chỉ xử lý khi sửa đúng cột Trạng thái duyệt
  if (e.range.getColumn() !== statusIdx + 1) return;

  const numRows = e.range.getNumRows();

  for (let i = 0; i < numRows; i++) {
    stampIrrelevantDateIfNeeded_(sheet, headers, row + i, null);
  }
}
function cleanupIrrelevantRowsAfter90Days() {
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(30000)) {
    return { ok: false, message: 'Hệ thống đang bận, vui lòng thử lại sau.' };
  }

  try {
    const ss = SpreadsheetApp.getActiveSpreadsheet();
    const sheet = ss.getSheetByName(WEBAPP_CONFIG.SHEET_NHAP);

    if (!sheet) {
      throw new Error('Không tìm thấy sheet: ' + WEBAPP_CONFIG.SHEET_NHAP);
    }

    const lastRow = sheet.getLastRow();
    const lastCol = sheet.getLastColumn();

    if (lastRow < 2) {
      return { ok: true, deleted_count: 0, message: 'Không có dữ liệu để dọn.' };
    }

    const headers = getHeaderInfo_(sheet).headers;

    const statusIdx = headers.indexOf(COL_TRANG_THAI_DUYET);
    const dateIdx = headers.indexOf(COL_NGAY_CHUYEN_TRANG_THAI);

    if (statusIdx < 0) {
      throw new Error('Thiếu cột: ' + COL_TRANG_THAI_DUYET);
    }

    if (dateIdx < 0) {
      throw new Error('Thiếu cột: ' + COL_NGAY_CHUYEN_TRANG_THAI);
    }

    const values = sheet
      .getRange(2, 1, lastRow - 1, lastCol)
      .getValues();

    const today = new Date();
    const rowsToDelete = [];

    for (let i = 0; i < values.length; i++) {
      const rowNumber = i + 2;
      const status = String(values[i][statusIdx] || '').trim();
      const changedAt = parseDateForCleanup_(values[i][dateIdx]);

      if (status !== STATUS_KHONG_LIEN_QUAN) continue;
      if (!changedAt) continue;

      const diffDays = Math.floor(
        (today.getTime() - changedAt.getTime()) / (1000 * 60 * 60 * 24)
      );

      if (diffDays >= IRRELEVANT_RETENTION_DAYS) {
        rowsToDelete.push(rowNumber);
      }
    }

    // Xóa từ dưới lên để không lệch dòng
    rowsToDelete
      .sort((a, b) => b - a)
      .forEach(rowNumber => {
        sheet.deleteRow(rowNumber);
      });

    if (rowsToDelete.length > 0) {
      sortSheetByColumnName_(WEBAPP_CONFIG.SHEET_NHAP, 'Ngày hiệu lực', false);

      appendDebugLog_('CLEANUP_KHONG_LIEN_QUAN_90D', {
        deleted_count: rowsToDelete.length,
        deleted_rows: rowsToDelete
      });
    }

    return {
      ok: true,
      deleted_count: rowsToDelete.length,
      message: 'Đã xóa ' + rowsToDelete.length + ' dòng Không liên quan quá 90 ngày.'
    };

  } catch (err) {
    appendDebugLog_('CLEANUP_KHONG_LIEN_QUAN_ERROR', {
      error_message: err.message,
      stack: err.stack || ''
    });

    return { ok: false, message: err.message };

  } finally {
    lock.releaseLock();
  }
}
function parseDateForCleanup_(value) {
  if (value instanceof Date && !isNaN(value.getTime())) {
    return value;
  }

  const text = String(value || '').trim();
  if (!text) return null;

  // Dạng dd/MM/yyyy hoặc dd/MM/yyyy HH:mm:ss
  const m = text.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})(?:\s+(\d{1,2}):(\d{1,2})(?::(\d{1,2}))?)?$/);

  if (m) {
    const day = Number(m[1]);
    const month = Number(m[2]) - 1;
    const year = Number(m[3]);
    const hour = Number(m[4] || 0);
    const minute = Number(m[5] || 0);
    const second = Number(m[6] || 0);

    const d = new Date(year, month, day, hour, minute, second);
    return isNaN(d.getTime()) ? null : d;
  }

  const fallback = new Date(text);
  return isNaN(fallback.getTime()) ? null : fallback;
}

function sortSheetByColumnName_(sheetName, columnName, ascending) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = ss.getSheetByName(sheetName);

  if (!sheet) {
    throw new Error('Không tìm thấy sheet: ' + sheetName);
  }

  const lastRow = sheet.getLastRow();
  const lastCol = sheet.getLastColumn();

  if (lastRow < 3) return;

  const headers = getHeaderInfo_(sheet).headers;
  const colIdx = headers.indexOf(columnName);

  if (colIdx < 0) {
    throw new Error('Không tìm thấy cột để sort: ' + columnName);
  }

  sheet
    .getRange(2, 1, lastRow - 1, lastCol)
    .sort({
      column: colIdx + 1,
      ascending: ascending
    });
}
function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('VBQPPL Tools')
    .addItem('Dọn Không liên quan quá 90 ngày', 'cleanupIrrelevantRowsAfter90Days')
    .addItem('Tạo trigger dọn Không liên quan hằng ngày', 'createDailyIrrelevantCleanupTrigger')
    .addToUi();
}
function createDailyIrrelevantCleanupTrigger() {
  const handler = 'cleanupIrrelevantRowsAfter90Days';

  // Xóa trigger cũ của cùng hàm để tránh tạo trùng
  ScriptApp.getProjectTriggers().forEach(trigger => {
    if (trigger.getHandlerFunction() === handler) {
      ScriptApp.deleteTrigger(trigger);
    }
  });

  ScriptApp
    .newTrigger(handler)
    .timeBased()
    .everyDays(1)
    .atHour(6)
    .create();

  appendDebugLog_('CREATE_TRIGGER_CLEANUP_90D', {
    message: 'Đã tạo trigger chạy hằng ngày cho cleanupIrrelevantRowsAfter90Days.'
  });

  return {
    ok: true,
    message: 'Đã tạo trigger dọn Không liên quan quá 90 ngày.'
  };
}
// Hàm hỗ trợ lọc các phần tử trùng lặp trong mảng
function uniqueList_(array) {
  if (!array || !Array.isArray(array)) return [];
  // Lọc các giá trị trống và loại bỏ trùng lặp
  return [...new Set(array.filter(function(item) {
    return item != null && item.toString().trim() !== '';
  }))];
}

/* =========================================================================================
 * P0 mục X — bảo trì WEBAPP_DEBUG_LOG ở mức tối thiểu (chỉ chặn phình vô hạn số dòng).
 * KHÔNG phải hệ thống retention/archive/summary đầy đủ — nằm ngoài phạm vi P0 security
 * hardening, xem P0_SECURITY_IMPLEMENTATION_REPORT.md mục "Nội dung chưa hoàn thành".
 * ========================================================================================= */

const LOG_MAINTENANCE_TRIGGER_HANDLER_ = 'executeWebAppDebugLogMaintenance_';
const LOG_MAINTENANCE_MAX_ROWS_ = 5000;

function executeWebAppDebugLogMaintenance_() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = ss.getSheetByName(WEBAPP_CONFIG.SHEET_LOG);
  if (!sheet) {
    return { ok: true, message: 'Sheet ' + WEBAPP_CONFIG.SHEET_LOG + ' chưa tồn tại, không có gì để dọn.', deleted_count: 0 };
  }

  const dataRowCount = sheet.getLastRow() - 1;
  if (dataRowCount <= LOG_MAINTENANCE_MAX_ROWS_) {
    return { ok: true, message: 'Số dòng log (' + dataRowCount + ') chưa vượt ngưỡng ' + LOG_MAINTENANCE_MAX_ROWS_ + '.', deleted_count: 0 };
  }

  const excess = dataRowCount - LOG_MAINTENANCE_MAX_ROWS_;
  // Xóa 1 block liên tiếp các dòng cũ nhất (ngay sau header) — KHÔNG deleteRow() lặp từng dòng.
  sheet.deleteRows(2, excess);
  SpreadsheetApp.flush();

  return { ok: true, message: 'Đã xóa ' + excess + ' dòng log cũ nhất để giữ dưới ' + LOG_MAINTENANCE_MAX_ROWS_ + ' dòng.', deleted_count: excess };
}

function installWebAppDebugLogMaintenanceTrigger_() {
  ScriptApp.getProjectTriggers().forEach(function(trigger) {
    if (trigger.getHandlerFunction() === LOG_MAINTENANCE_TRIGGER_HANDLER_) {
      ScriptApp.deleteTrigger(trigger);
    }
  });

  ScriptApp.newTrigger(LOG_MAINTENANCE_TRIGGER_HANDLER_).timeBased().everyDays(1).atHour(5).create();

  return { ok: true, message: 'Đã cài trigger dọn ' + WEBAPP_CONFIG.SHEET_LOG + ' chạy hằng ngày khoảng 05:00.' };
}

function removeWebAppDebugLogMaintenanceTrigger_() {
  let removedCount = 0;
  ScriptApp.getProjectTriggers().forEach(function(trigger) {
    if (trigger.getHandlerFunction() === LOG_MAINTENANCE_TRIGGER_HANDLER_) {
      ScriptApp.deleteTrigger(trigger);
      removedCount++;
    }
  });

  return { ok: true, removed_count: removedCount, message: 'Đã xóa ' + removedCount + ' trigger dọn log.' };
}

// Public wrapper (không dấu gạch dưới) — chạy thủ công từ Apps Script Editor / menu.
function installWebAppDebugLogMaintenanceTrigger() {
  return installWebAppDebugLogMaintenanceTrigger_();
}

function removeWebAppDebugLogMaintenanceTrigger() {
  return removeWebAppDebugLogMaintenanceTrigger_();
}
