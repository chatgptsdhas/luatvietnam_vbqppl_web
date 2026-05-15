/**
 * MODULE XỬ LÝ VĂN BẢN HẾT HIỆU LỰC / BỊ BÃI BỎ / THAY THẾ
 * Tích hợp chế độ kiểm thử DRY_RUN an toàn.
 */

const EXPIRED_CONFIG = {
  DRY_RUN: true, // TRUE: Chỉ ghi log, KHÔNG XÓA THẬT. Đổi thành FALSE khi đã test ổn định.
  SHEET_NAME: 'VBQPPL_HetHieuLuc',
  KEYWORDS_STRONG: ['hết hiệu lực', 'bị bãi bỏ', 'được thay thế bởi', 'thay thế', 'chấm dứt hiệu lực', 'không còn hiệu lực'],
  KEYWORDS_PARTIAL: ['một phần', 'hết hiệu lực một phần', 'bãi bỏ một phần', 'thay thế một phần'],
  TARGET_SECTIONS: ['điều khoản thi hành', 'hiệu lực thi hành', 'điều khoản chuyển tiếp'],
  RELATION_COLUMNS: [
    'Căn cứ pháp lý', 'Hướng dẫn thực hiện', 'Sửa đổi, bổ sung cho', 
    'Sửa đổi, bổ sung bởi', 'Nội dung căn cứ', 'Gợi ý căn cứ pháp lý', 
    'Văn bản chưa có trong danh mục', 'Ghi chú quan hệ pháp lý'
  ]
};

/**
 * 1. HÀM KHỞI TẠO SHEET (Tự động chạy nếu chưa có sheet)
 */
function initExpiredSheet_() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sheet = ss.getSheetByName(EXPIRED_CONFIG.SHEET_NAME);
  if (!sheet) {
    sheet = ss.insertSheet(EXPIRED_CONFIG.SHEET_NAME);
    const headers = [
      'Thời gian phát hiện', 'Số hiệu bị xử lý', 'Tên văn bản bị xử lý', 
      'Số hiệu văn bản mới', 'Tên văn bản mới', 'Lý do nhận diện', 
      'Ngày hết hiệu lực áp dụng', 'Trạng thái xử lý', 'Câu nguồn', 
      'Có cụm một phần', 'Dry run', 'Thời gian xóa thật', 
      'Dữ liệu dòng gốc JSON', 'Ghi chú xử lý'
    ];
    sheet.appendRow(headers);
    sheet.getRange("A1:N1").setFontWeight("bold").setBackground("#f3f3f3");
    sheet.setFrozenRows(1);
  }
  return sheet;
}

/**
 * 2. HÀM QUÉT VÀ BÓC TÁCH (Chạy khi bấm nút Chuyển trên Web)
 */
/**
 * 2. HÀM QUÉT VÀ BÓC TÁCH (Chạy khi bấm nút Chuyển trên Web)
 */
function scanAndLogExpiredDocs(sourceSoHieu, sourceTen, sourceLink) {
  if (!sourceLink || typeof sourceLink !== 'string' || sourceLink.indexOf('http') === -1) return;
  
  const sheetLog = initExpiredSheet_();
  let htmlContent = '';
  
  try {
    // NÂNG CẤP: Giả lập trình duyệt Chrome thật để vượt qua tường lửa chặn Bot
    const options = {
      muteHttpExceptions: true, 
      timeout: 15000,
      headers: {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7"
      }
    };
    
    const response = UrlFetchApp.fetch(sourceLink, options);
    if (response.getResponseCode() !== 200) throw new Error("Mã lỗi HTTP: " + response.getResponseCode());
    htmlContent = response.getContentText();
  } catch (e) {
    // NÂNG CẤP: Sắp xếp lại chuẩn xác thứ tự tham số để không bị lệch cột Google Sheet
    // logExpiredResult_(sheet, soHieuCu, reason, sentence, soHieuMoi, tenMoi, maxDateStr, isPartial, trangThai)
    logExpiredResult_(
      sheetLog, 
      '',                  // Không có số hiệu cũ vì bị lỗi
      'Lỗi tải link',      // Lý do nhận diện
      'Chi tiết lỗi: ' + e.message, // Câu nguồn (Chứa nội dung lỗi)
      sourceSoHieu,        // Số hiệu văn bản mới
      sourceTen,           // Tên văn bản mới
      '',                  // Ngày hết hiệu lực
      false,               // Không có cụm một phần
      'Thất bại - Cần check tay' // Trạng thái xử lý
    );
    return;
  }

  // Loại bỏ tag HTML để lấy text thuần
  const textContent = htmlContent.replace(/<[^>]*>?/gm, ' ').replace(/\s+/g, ' ');
  
  // Tìm vùng chứa Điều khoản thi hành
  let targetBlock = '';
  for (let section of EXPIRED_CONFIG.TARGET_SECTIONS) {
    const regex = new RegExp(section + "[\\s\\S]*?(?=(Điều \\d+|CHƯƠNG|[A-Z]{5,}|$))", "i");
    const match = textContent.match(regex);
    if (match) {
      targetBlock = match[0];
      break; // Chỉ lấy vùng đầu tiên tìm thấy
    }
  }

  if (!targetBlock) return; // Không tìm thấy phần thi hành thì bỏ qua

  // Phân tích các câu trong vùng target
  const sentences = targetBlock.split(/[.;]/);
  
  for (let sentence of sentences) {
    sentence = sentence.trim();
    if (sentence.length < 10) continue;

    // Kiểm tra từ khóa mạnh
    let foundReason = '';
    for (let kw of EXPIRED_CONFIG.KEYWORDS_STRONG) {
      if (sentence.toLowerCase().includes(kw)) {
        foundReason = kw;
        break;
      }
    }

    if (!foundReason) continue;

    // Kiểm tra "một phần"
    let isPartial = false;
    for (let kw of EXPIRED_CONFIG.KEYWORDS_PARTIAL) {
      if (sentence.toLowerCase().includes(kw)) {
        isPartial = true;
        break;
      }
    }

    // Bóc tách Số hiệu cũ bị bãi bỏ (Tìm các chuỗi có định dạng xx/xxxx/yy-zz)
    const soHieuMatches = sentence.match(/\b\d+[\/-]\d+[\/\w\-]+\b/g);
    if (!soHieuMatches) continue;

    // Bóc tách ngày hết hiệu lực
    const dateMatches = sentence.match(/\b\d{1,2}[\/-]\d{1,2}[\/-]\d{4}\b/g);
    let maxDate = null;
    let maxDateStr = '';
    
    if (dateMatches) {
      dateMatches.forEach(d => {
        const parts = d.split(/[\/-]/);
        if(parts.length === 3) {
          const dateObj = new Date(parts[2], parts[1] - 1, parts[0]);
          if (!maxDate || dateObj > maxDate) {
            maxDate = dateObj;
            maxDateStr = d;
          }
        }
      });
    }

    // Ghi nhận cho từng số hiệu tìm thấy
    for (let soHieuCu of soHieuMatches) {
      // Bỏ qua chính số hiệu của văn bản mới
      if (soHieuCu.toLowerCase() === sourceSoHieu.toLowerCase()) continue;

      let trangThai = '';
      if (isPartial) {
        trangThai = 'Cần kiểm tra thủ công';
      } else if (!maxDate) {
        trangThai = 'Cần kiểm tra thủ công (Không rõ ngày)';
      } else {
        const today = new Date();
        today.setHours(0,0,0,0);
        if (maxDate > today) {
          trangThai = 'Chưa xóa - chưa đến ngày hết hiệu lực';
        } else {
          trangThai = 'Chờ xóa tự động'; // Sẽ được cron job quét và xóa
        }
      }

      logExpiredResult_(
        sheetLog, 
        soHieuCu, 
        foundReason, 
        sentence, 
        sourceSoHieu, 
        sourceTen, 
        maxDateStr, 
        isPartial, 
        trangThai
      );
    }
  }
}

/**
 * 3. HÀM CRON JOB - CHẠY HẰNG NGÀY ĐỂ XÓA THẬT
 * Cần thiết lập Trigger Time-driven chạy hàm này hằng ngày lúc 06:00.
 */
function processScheduledExpiredDocuments() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheetExpired = initExpiredSheet_();
  // Ở file này gọi WEBAPP_CONFIG sẽ lấy từ file webapp.gs chạy cùng
  const sheetVbqppl = ss.getSheetByName(WEBAPP_CONFIG.SHEET_VBQPPL);
  const sheetNhap = ss.getSheetByName(WEBAPP_CONFIG.SHEET_NHAP);

  const expData = sheetExpired.getDataRange().getValues();
  if (expData.length < 2) return;
  const expHeaders = expData[0];
  const idxSoHieuCu = expHeaders.indexOf('Số hiệu bị xử lý');
  const idxNgayHet = expHeaders.indexOf('Ngày hết hiệu lực áp dụng');
  const idxTrangThai = expHeaders.indexOf('Trạng thái xử lý');
  const idxThoiGianXoa = expHeaders.indexOf('Thời gian xóa thật');

  const today = new Date();
  today.setHours(0,0,0,0);

  // Lấy toàn bộ Số hiệu cần xóa hôm nay
  const toDeleteMap = {}; // Key: SoHieu, Value: Array of Row Index in Expired Sheet

  for (let i = 1; i < expData.length; i++) {
    const status = String(expData[i][idxTrangThai] || '').trim();
    const dateStr = String(expData[i][idxNgayHet] || '').trim();
    
    if (status === 'Chờ xóa tự động' || status === 'Chưa xóa - chưa đến ngày hết hiệu lực') {
      let isDue = false;
      if (dateStr) {
        const parts = dateStr.split(/[\/-]/);
        if(parts.length === 3) {
          const expDate = new Date(parts[2], parts[1] - 1, parts[0]);
          if (expDate <= today) isDue = true;
        }
      } else {
        // Nếu không có ngày nhưng đang chờ xóa, coi như đến hạn
        isDue = true; 
      }

      if (isDue) {
        const soHieu = String(expData[i][idxSoHieuCu]).trim();
        if (soHieu) {
          if (!toDeleteMap[soHieu]) toDeleteMap[soHieu] = [];
          toDeleteMap[soHieu].push(i + 1); // Row index (1-based)
        }
      }
    }
  }

  const soHieusToDelete = Object.keys(toDeleteMap);
  if (soHieusToDelete.length === 0) return;

  // Nếu là DRY RUN, chỉ đổi trạng thái thành "Đã mô phỏng xóa (DRY RUN)"
  if (EXPIRED_CONFIG.DRY_RUN) {
    soHieusToDelete.forEach(soHieu => {
      toDeleteMap[soHieu].forEach(rowIdx => {
        sheetExpired.getRange(rowIdx, idxTrangThai + 1).setValue('Đã mô phỏng xóa (DRY_RUN)');
        sheetExpired.getRange(rowIdx, idxThoiGianXoa + 1).setValue(new Date());
      });
    });
    return;
  }

  // NẾU DRY_RUN = FALSE -> BẮT ĐẦU XÓA THẬT
  if (sheetVbqppl) deleteRowsAndReferences_(sheetVbqppl, soHieusToDelete);
  if (sheetNhap) deleteRowsAndReferences_(sheetNhap, soHieusToDelete);

  // Cập nhật lại sheet VBQPPL_HetHieuLuc
  soHieusToDelete.forEach(soHieu => {
    toDeleteMap[soHieu].forEach(rowIdx => {
      sheetExpired.getRange(rowIdx, idxTrangThai + 1).setValue('Đã xóa theo lịch');
      sheetExpired.getRange(rowIdx, idxThoiGianXoa + 1).setValue(new Date());
    });
  });
}

/**
 * Hàm phụ trợ: Ghi log vào Sheet Hết Hiệu Lực
 */
function logExpiredResult_(sheet, soHieuCu, reason, sentence, soHieuMoi, tenMoi, maxDateStr, isPartial, trangThai) {
  sheet.appendRow([
    new Date(),
    soHieuCu || '',
    '', // Chưa bóc tách được Tên văn bản cũ từ HTML một cách an toàn
    soHieuMoi,
    tenMoi,
    reason,
    maxDateStr,
    trangThai,
    sentence,
    isPartial ? 'CÓ' : 'KHÔNG',
    EXPIRED_CONFIG.DRY_RUN ? 'TRUE' : 'FALSE',
    '', // Thời gian xóa thật (Để trống)
    '', // Dữ liệu JSON (Có thể bổ sung sau)
    'Hệ thống tự động quét từ nội dung văn bản mới'
  ]);
}

/**
 * Hàm phụ trợ: Quét ngược từ dưới lên để XÓA DÒNG và XÓA THAM CHIẾU
 */
function deleteRowsAndReferences_(sheet, soHieusToDelete) {
  const lastRow = sheet.getLastRow();
  const lastCol = sheet.getLastColumn();
  if (lastRow < 2 || lastCol < 1) return;

  const headers = sheet.getRange(1, 1, 1, lastCol).getValues()[0].map(String);
  const idxSoHieu = headers.indexOf('Số hiệu');
  if (idxSoHieu === -1) return;

  // Lấy chỉ số các cột quan hệ (nếu có tồn tại trong sheet)
  const relColIndexes = [];
  EXPIRED_CONFIG.RELATION_COLUMNS.forEach(colName => {
    const idx = headers.indexOf(colName);
    if (idx !== -1) relColIndexes.push(idx);
  });

  const data = sheet.getRange(1, 1, lastRow, lastCol).getValues();
  const lowerSoHieus = soHieusToDelete.map(s => s.toLowerCase());

  // Quét từ dưới lên trên để xóa dòng không bị lệch index
  for (let r = lastRow - 1; r >= 1; r--) {
    const rowSoHieu = String(data[r][idxSoHieu]).trim().toLowerCase();
    
    // NẾU TÌM THẤY DÒNG CHỨA SỐ HIỆU HẾT HIỆU LỰC -> XÓA CẢ DÒNG
    if (lowerSoHieus.includes(rowSoHieu)) {
      sheet.deleteRow(r + 1);
      continue; // Bỏ qua phần cập nhật tham chiếu bên dưới vì dòng đã bị xóa
    }

    // NẾU LÀ DÒNG BÌNH THƯỜNG -> QUÉT VÀ XÓA SỐ HIỆU Ở CÁC CỘT QUAN HỆ
    let isRowModified = false;
    relColIndexes.forEach(colIdx => {
      const cellValue = String(data[r][colIdx] || '').trim();
      if (cellValue) {
        // Tách chuỗi theo dấu phẩy hoặc xuống dòng
        let items = cellValue.split(/[\n,;]+/).map(s => s.trim()).filter(Boolean);
        let originalLength = items.length;
        
        // Lọc bỏ các phần tử bị trùng với số hiệu hết hiệu lực
        items = items.filter(item => !lowerSoHieus.includes(item.toLowerCase()));
        
        // Nếu mảng bị rút ngắn, tức là có thay đổi
        if (items.length < originalLength) {
          data[r][colIdx] = items.join(', '); // Nối lại bằng dấu phẩy
          isRowModified = true;
        }
      }
    });

    // Cập nhật lại dòng nếu có tham chiếu bị xóa
    if (isRowModified) {
      // Lấy data đã sửa của r, ghi đè lên sheet (r + 1 là số thứ tự dòng thực tế)
      sheet.getRange(r + 1, 1, 1, lastCol).setValues([data[r]]);
    }
  }
}