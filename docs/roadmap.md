# 로드맵

## Phase 1 — 화면 프로토타입 ✅ (현재)
- 정적 HTML/CSS/JS 대시보드
- 박스오피스 / 예매율 / 프로모션 매트릭스 / 굿즈 참고 섹션
- 목업 데이터로 화면 검증

## Phase 2 — KOFIC 데이터 연동 🔄 (진행 중)
- ✅ KOFIC OpenAPI 키 설정 (`.env` / `KOFIC_API_KEY`)
- ✅ `searchDailyBoxOfficeList` 호출 스크립트 `scripts/fetch_boxoffice.py`
- ✅ 결과를 `assets/data/boxoffice.json` 으로 저장
- ✅ 대시보드가 fetch 로 읽고, 실패 시 목업 폴백
- ⏭ 일배치 자동화 (cron / GitHub Actions) — Phase 7 과 연계

## Phase 3 — KOBIS 실시간 예매율 스크래퍼 🔄 (진행 중)
- ✅ `findRealTicketList.do` HTML 표 파싱 — `scripts/fetch_booking.py`
- ✅ 결과를 `assets/data/booking.json` 으로 저장
- ✅ 대시보드가 fetch 로 읽고, 실패 시 목업 폴백
- ✅ 직전 수집분과 movieCd 기준 비교해 예매율 delta 계산
- ⏭ 15~60분 주기 자동 수집 (cron / GitHub Actions) — Phase 7 연계
- ⏭ 시계열 누적 저장 (시간대별 예매율 변화 추적) — Phase 5/6 연계

## Phase 4 — 4사 프로모션 크롤러 🔄 (진행 중)
- ✅ 롯데시네마 파일럿 — `scripts/fetch_promotions_lotte.py`
  - LCWS 이벤트 API 추출 (쿠키+Referer, EventClassificationCode 10/20/40)
  - 쿠폰/무대인사/굿즈/기타 자동 분류
  - `<영화명>` 파싱 → boxoffice/booking 의 movieCd 매칭
  - `assets/data/promotions_lotte.json` + 대시보드 전용 패널
- ✅ 메가박스 크롤러 — `scripts/fetch_promotions_megabox.py`
  - `eventMngDiv.do` HTML 조각 파싱, 롯데와 동일 스키마·패널
- ⛔ CGV — `robots.txt` 가 검색엔진 외 모든 봇 전면 차단(`Disallow: /`) → 보류
- ⏭ 씨네큐 이벤트 크롤러
- ⏭ 4사 통합 → 프로모션 영향 매트릭스 실데이터 연결 (목업 대체)

## Phase 5 — DB 저장 & 누적
- SQLite (개발) → PostgreSQL (운영)
- 스키마: `promotion`, `booking_metrics`, `movie` 3개 테이블
- 일배치로 매일 데이터 누적 → 시계열 분석 가능

## Phase 6 — 영향도 분석 고도화
- Pre/Post uplift 자동 계산
  - 프로모션 시작 D-3 평균 예매율 vs D-Day~D+2 평균
- 체인 간 상대비교 (같은 영화에서 프로모션 한 체인 vs 안 한 체인)
- 누적 효과 분석
- 통계적 유의성 검정

## Phase 7 — 알림 & 자동화
- 효율 0.5× 미만 또는 1.5× 초과 영화 슬랙 알림
- 일간/주간 자동 리포트 메일 발송
- GitHub Actions로 일배치 + 정적 사이트 자동 배포 (GitHub Pages)
