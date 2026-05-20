/**
 * sheets_webapp.gs — 시네마 프로모션 백데이터 → 구글 시트 누적 (Apps Script 웹앱)
 * --------------------------------------------------------------------------
 * extract_backdata.py 가 매일 오늘자 행을 POST 하면, 같은 날짜 행은 교체(upsert)
 * 하고 나머지는 그대로 누적한다. 파이썬은 urllib POST 만 하므로 의존성 0.
 *
 * [최초 1회 설정]
 *  1) 구글 시트를 새로 만든다(누적 저장용).
 *  2) 확장 프로그램 > Apps Script 를 열고, 이 파일 내용을 통째로 붙여넣는다.
 *  3) 아래 TOKEN 을 임의의 비밀 문자열로 바꾼다(파이썬 .env 의 SHEETS_TOKEN 과 동일하게).
 *  4) 배포 > 새 배포 > 유형: 웹 앱
 *       - 실행 계정: 나
 *       - 액세스 권한: "모든 사용자"(Anyone) ← 로그인 없이 호출 가능해야 함.
 *         ("Google 계정이 있는 사용자"는 OAuth 로그인 필요 → urllib POST 불가)
 *         공개돼도 아래 TOKEN 검증이 무단 쓰기를 막는다.
 *     배포 후 나오는 "웹 앱 URL"(.../exec)을 복사.
 *  5) 프로젝트 루트 .env 에 아래 두 줄 추가:
 *       SHEETS_WEBAPP_URL=복사한_웹앱_URL
 *       SHEETS_TOKEN=3번에서_정한_비밀문자열
 *  6) 코드 수정 후 재배포할 땐 "배포 관리 > 편집 > 버전: 새 버전"으로 갱신.
 */

const TOKEN = 'CHANGE_ME_SECRET';   // ← 파이썬 .env 의 SHEETS_TOKEN 과 똑같이 바꿀 것
const SHEET_NAME = '프로모션 일별 누적';   // 누적할 시트(탭) 이름

function doPost(e) {
  try {
    const body = JSON.parse(e.postData.contents);
    if (TOKEN && body.token !== TOKEN) {
      return _json({ ok: false, error: 'invalid token' });
    }
    const ss = SpreadsheetApp.getActiveSpreadsheet();
    const sh = ss.getSheetByName(SHEET_NAME) || ss.insertSheet(SHEET_NAME);

    const header = body.header || [];
    const rows = body.rows || [];
    const date = body.date;

    // 헤더 보장(비어 있으면 1행에 기록)
    if (sh.getLastRow() === 0 && header.length) {
      sh.appendRow(header);
    }

    // 같은 날짜(1열) 행 제거 → upsert
    if (date && sh.getLastRow() > 1) {
      const colA = sh.getRange(2, 1, sh.getLastRow() - 1, 1).getValues();
      for (let i = colA.length - 1; i >= 0; i--) {
        if (String(colA[i][0]) === String(date)) {
          sh.deleteRow(i + 2);
        }
      }
    }

    // 신규 행 일괄 추가
    if (rows.length) {
      sh.getRange(sh.getLastRow() + 1, 1, rows.length, rows[0].length)
        .setValues(rows);
    }
    return _json({ ok: true, date: date, added: rows.length });
  } catch (err) {
    return _json({ ok: false, error: String(err) });
  }
}

function _json(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}
