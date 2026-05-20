# 데이터 출처 정리

## 1. KOFIC / KOBIS

### KOFIC OpenAPI (안정적, 권장)
- 사이트: https://www.kobis.or.kr/kobisopenapi
- 키 발급 후 사용
- 주요 엔드포인트
  - `searchDailyBoxOfficeList` — 일별 박스오피스
  - `searchWeeklyBoxOfficeList` — 주간/주말 박스오피스
  - `searchMovieList` / `searchMovieInfo` — 영화 정보 (영화코드 발급)
- 영화 식별 키 `movieCd` 를 모든 테이블의 조인 키로 사용 권장.

### KOBIS 실시간 예매율 (스크래핑 필요)
- 페이지: https://www.kobis.or.kr/kobis/business/stat/boxs/findRealTicketList.do
- OpenAPI에 직접 엔드포인트 없음
- **데이터 조회 URL** (서버 렌더링 HTML 표를 그대로 반환 · 브라우저 불필요):
  `findRealTicketList.do?loadEnd=0&dmlMode=search&allMovieYn=Y`
- 표 컬럼: 순위 / 영화명(+movieCd) / 개봉일 / 예매율 / 예매매출액 / 누적매출액 / 예매관객수 / 누적관객수
- `movieCd` 는 영화명 링크 `<a onclick="mstView('movie','...')">` 에서 추출 → 박스오피스와 조인 가능
- 인코딩은 `UTF-8` (응답 헤더 `charset=UTF-8` 및 바이트 검증 일치)
- 구현: `scripts/fetch_booking.py` (표준 라이브러리만 사용)
- KOBIS 가 증감 데이터를 안 주므로, delta 는 직전 수집분과 비교해 계산 (15~60분 주기 수집 권장)

## 2. 프로모션 데이터 (4사)

| 체인 | 굿즈 수량 공개 | 쿠폰 정보 | 무대인사 |
|---|---|---|---|
| **CGV** | 일부 지점만 경품현황 페이지 제공 (용산, 영등포, 왕십리, 울산삼산, 천안터미널, 판교 등) | 서프라이즈/스피드/서온쿠 카테고리 | 이벤트 페이지 |
| **롯데시네마** | 잔여 수량을 "50개 이상", "50~99" 등 구간으로 제공 (앱/웹) | 무비싸다구 | 이벤트 페이지 |
| **메가박스** | 2025년 4월부터 이벤트 페이지에서 수량 조회 가능 (상영 후 증정으로 정책 변경) | 빵원티켓 / 빵원티켓 PLUS | 이벤트 페이지 |
| **씨네큐** | 공개 데이터 거의 없음 | 무비0원딜 | 이벤트 페이지 |

### 롯데시네마 이벤트 API (파일럿 — 추출 완료)

롯데시네마 이벤트 페이지는 React SPA 라 HTML 스크래핑이 안 되고, 내부
LCWS API 를 호출해야 한다. 구현: `scripts/fetch_promotions_lotte.py`

- **호출 절차**
  1. 쿠키 자(cookie jar)로 `GET https://www.lottecinema.co.kr/NLCHS/Event`
     → 세션 쿠키 `WMONID`, `TS...` 획득
  2. `POST https://www.lottecinema.co.kr/LCWS/Event/EventData.aspx`
     - 헤더: `Content-Type: multipart/form-data`,
       `Referer: https://www.lottecinema.co.kr/NLCHS/Event`, 1번 쿠키
     - 바디: multipart 필드 `paramList` = JSON
       (`MethodName:"GetEventLists"`, `channelType:"HO"`, `osType:"PC"`,
       `CinemaID:""`, `EventClassificationCode:<코드>`, `PageSize:100` 등)
  - ⚠ **쿠키·Referer 가 없으면 .NET NullReference 에러** 를 반환한다
- **EventClassificationCode**: `10`=쿠폰/무비싸다구, `20`=특전/굿즈/SNS,
  `40`=무대인사/시사회, `30`=극장별, `0`=전체
- 응답 `Items[]` 의 `EventName` 은 영화명을 `<...>` 꺾쇠로 표기 → 영화 매칭에 사용
- 응답 인코딩 UTF-8

### 메가박스 이벤트 API (추출 완료)

메가박스는 전통적 JSP 사이트로 이벤트 목록이 서버 렌더링 HTML 로 내려온다.
구현: `scripts/fetch_promotions_megabox.py`

- **이벤트 목록**: `POST https://www.megabox.co.kr/on/oh/ohe/Event/eventMngDiv.do`
  - params: `currentPage`(페이지), `eventStatCd=ONG`(진행중)
  - 헤더: `Content-Type: application/x-www-form-urlencoded`,
    `Referer: https://www.megabox.co.kr/event`, `X-Requested-With: XMLHttpRequest`
  - 응답: 이벤트 카드 HTML 조각 — `<a data-no="..." class="eventBtn">` 안에
    `<p class="tit">`(제목)·`<p class="date">`(기간)
  - 페이지당 12건, `currentPage` 증가로 페이징. 인코딩 UTF-8.
- 제목의 `<영화명>` 으로 movieCd 매칭 (롯데와 동일 방식)
- robots.txt 파일 없음(명시적 금지 없음), 브라우저 불필요

### CGV — 자동 크롤링 보류

CGV(`cgv.co.kr`)는 `robots.txt` 에서 검색엔진(구글·네이버·다음·빙 등)을 제외한
모든 User-agent 를 `Disallow: /` 로 전면 차단한다. 명시적 거부 의사이므로 자동
크롤러 대상에서 제외한다. (기술적으로도 Next.js App Router SPA + 봇 차단)

### 굿즈 수량 합산이 어려운 이유

1. **단위가 다름** — 롯데(구간) / CGV(지점별 잔여) / 메가박스(실수량) / 씨네큐(미공개)
2. **시점이 다름** — 초기 총 수량 ≠ 잔여 수량
3. **공개 범위가 다름** — CGV는 6개 지점만, 롯데는 전 지점

→ 따라서 본 대시보드는 굿즈를 **점유율 계산에서 제외**하고 진행 영화관 **개소 수**로만 규모를 표기.

### 참고할 만한 외부 집계 사이트
- Cinemagoods.com — 4사 굿즈/쿠폰을 통합 표시
- Goodstrades.kr — 영화 굿즈 정보 · 특전 수량 (롯데/메가 위주)

이런 사이트는 참고용이고, 실제 데이터는 각 체인 공식 페이지에서 직접 받는 게 안정적.

## 3. 권장 스택

- **수집**: Python + `requests` + `playwright` (또는 `selenium`)
- **스케줄**: cron / GitHub Actions / Airflow
- **저장**: 초기엔 SQLite, 데이터 누적 후 PostgreSQL
- **대시보드**: 현재 정적 HTML, 추후 Metabase/Superset 고려

## 4. 수집 주기 가이드

| 데이터 | 권장 주기 |
|---|---|
| 박스오피스 (KOFIC) | 일 1회 (전일자) |
| 실시간 예매율 (KOBIS) | 15~60분 |
| 프로모션 진행 정보 (4사) | 일 2~3회 |
| 굿즈 잔여 수량 | 1~3시간 (필요 시) |
