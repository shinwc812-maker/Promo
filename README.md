# Cinema Promotion Dashboard

영화관 4사(CGV · 롯데시네마 · 메가박스 · 씨네큐)의 프로모션 진행 현황(쿠폰 · 무대인사 · 굿즈 등)과 KOFIC 실시간 예매율을 한 화면에서 비교하여, 프로모션이 예매율에 얼마나 기여하는지 정량 분석하는 내부 보고용 대시보드입니다.

## 주요 화면

- **금일 박스오피스 TOP 10** (KOFIC OpenAPI)
- **실시간 예매율 TOP 10** (KOBIS 실시간 예매율)
- **프로모션 영향 매트릭스** — 영화별 쿠폰/무대인사/총좌석의 절대값과 TOP 10 합계 대비 점유율, 예매율 점유율과 비교한 **프로모션 효율(배수)**
- **굿즈 이벤트 진행 현황** (참고용) — 영화관 개소 수로 규모만 표시

## 폴더 구조

```
cinema-promotion-dashboard/
├── index.html              # 진입점
├── assets/
│   ├── css/
│   │   └── styles.css      # 전체 스타일
│   └── js/
│       ├── data.js         # 데이터 (현재는 목업, 추후 실데이터 교체)
│       └── dashboard.js    # 렌더링 로직
├── docs/
│   ├── data-sources.md     # 데이터 출처 및 수집 방안
│   └── roadmap.md          # 단계별 진행 계획
├── .gitignore
└── README.md
```

## 빠른 시작

저장소를 클론한 뒤 정적 파일이라 어떤 방식으로든 띄울 수 있습니다.

```bash
# 1) Python 내장 서버
python3 -m http.server 8000

# 2) Node 환경
npx serve .

# 3) 그냥 더블클릭으로 index.html 열기도 가능
```

브라우저에서 http://localhost:8000 으로 접속.

## 데이터 교체 방법

목업 데이터는 `assets/js/data.js`의 `boxOffice` / `bookingRate` / `promotions` 세 배열로 정의되어 있습니다. 각 배열의 키는 KOFIC 응답 스키마와 거의 동일하게 맞춰뒀으니, 실제 API/스크래핑 결과를 같은 형태로 만들어 교체하면 화면 로직은 그대로 동작합니다.

| 배열 | 추천 출처 |
|---|---|
| `boxOffice`   | KOFIC OpenAPI `searchDailyBoxOfficeList` |
| `bookingRate` | KOBIS 실시간 예매율 페이지 스크래핑 (OpenAPI 미제공) |
| `promotions`  | CGV / LOTTE / MEGA / CINEQ 이벤트 페이지 크롤링 결과를 `movieCd` 기준 조인 |

자세한 출처별 가용성과 한계는 [`docs/data-sources.md`](docs/data-sources.md) 참고.

## KOFIC 박스오피스 실데이터 연동

박스오피스 TOP 10 은 KOFIC OpenAPI 실데이터로 연동되어 있습니다.

### 1) API 키 설정

[KOFIC OpenAPI](https://www.kobis.or.kr/kobisopenapi) 에서 키를 발급받은 뒤,
`.env.example` 을 `.env` 로 복사하고 키를 채워넣습니다.

```
KOFIC_API_KEY=발급받은키
```

`.env` 는 `.gitignore` 에 등록되어 있어 깃에 올라가지 않습니다.

### 2) 데이터 수집

```bash
python scripts/fetch_boxoffice.py            # 어제 날짜 (기본)
python scripts/fetch_boxoffice.py 20260515   # 특정 날짜 지정
```

실행하면 `assets/data/boxoffice.json` 이 생성/갱신됩니다.
파이썬 표준 라이브러리만 사용하므로 `pip install` 은 필요 없습니다.

### 3) 동작 방식

대시보드는 `assets/data/boxoffice.json` 을 `fetch` 로 읽습니다.
파일이 없거나(스크립트 미실행) `file://` 로 직접 열어 fetch 가 막히면
`data.js` 의 목업 데이터로 자동 폴백하며, 패널 태그에 `목업` 으로 표시됩니다.
→ **실데이터를 보려면 로컬 서버로 띄워야 합니다** (`python3 -m http.server 8000`).

## KOBIS 실시간 예매율 연동

실시간 예매율 TOP 10 은 KOBIS 실시간 예매율 페이지 스크래핑으로 연동됩니다.
KOFIC OpenAPI 에는 실시간 예매율 엔드포인트가 없지만, 데이터가 서버 렌더링
HTML 표로 내려와 **브라우저(playwright 등) 없이** 표준 라이브러리만으로 수집합니다.

### 데이터 수집

```bash
python scripts/fetch_booking.py
```

API 키가 필요 없으며, 실행하면 `assets/data/booking.json` 이 생성/갱신됩니다.

### delta(직전 대비 증감)

예매율 증감(`delta`)은 KOBIS 가 제공하지 않으므로, **직전에 저장된
`booking.json` 과 `movieCd` 기준으로 비교**해 계산합니다.
→ 15~60분 주기로 반복 실행해야 의미 있는 증감이 표시됩니다.
   (첫 실행은 비교 대상이 없어 `—` 로 표시)

## 롯데시네마 프로모션 크롤러 (Phase 4 파일럿)

4사 프로모션 크롤러의 롯데시네마 파일럿입니다. 롯데시네마 이벤트 API 를
호출해 영화별 쿠폰·무대인사·굿즈 이벤트를 분류·집계합니다.

### 데이터 수집

```bash
python scripts/fetch_promotions_lotte.py
```

API 키가 필요 없으며, 실행하면 `assets/data/promotions_lotte.json` 이
생성/갱신되고 대시보드의 "롯데시네마 프로모션 현황" 패널에 반영됩니다.

### 동작

- 롯데 이벤트 API(`LCWS/Event/EventData.aspx`)에서 진행 중 이벤트 수집
- 이벤트명을 쿠폰 / 무대인사 / 굿즈·특전 / 기타로 분류
- 이벤트명의 `<영화명>` 을 `boxoffice.json`·`booking.json` 의 `movieCd` 와 매칭
- 박스오피스·예매율에 없는 영화(개봉 전·예술영화 등)는 미매칭으로 분류

자세한 API 구조는 [`docs/data-sources.md`](docs/data-sources.md) 참고.

## 메가박스 프로모션 크롤러 (Phase 4)

메가박스 이벤트 API(`eventMngDiv.do`)를 호출해 영화별 쿠폰·무대인사·굿즈
이벤트를 분류·집계합니다.

```bash
python scripts/fetch_promotions_megabox.py
```

`assets/data/promotions_megabox.json` 이 생성되고 대시보드 "메가박스 프로모션
현황" 패널에 반영됩니다. 분류·매칭 방식은 롯데 크롤러와 동일합니다.

> CGV 는 `robots.txt` 가 검색엔진 외 모든 봇을 차단(`Disallow: /`)하고 있어
> 자동 크롤링 대상에서 제외했습니다.

## 효율 지표

```
프로모션 효율 = 예매율 점유율 ÷ 프로모션 평균 점유율(쿠폰·무대인사·총좌석 3개 평균)
```

- **1.10× 이상** — 프로모션 투입 대비 예매율 초과 (효율 좋음)
- **0.90 ~ 1.10×** — 정상 범위
- **0.90× 미만** — 프로모션 대비 부진

> 굿즈는 체인별 수량 공개 단위가 달라(롯데는 구간 표시, CGV는 일부 지점만, 메가박스는 최근 정확 수량 공개) 점유율 계산에서 제외하고 참고 섹션에 개소 수로만 표시합니다.

## 진행 단계

[`docs/roadmap.md`](docs/roadmap.md) 참고.

1. ✅ 화면 프로토타입
2. ✅ KOFIC OpenAPI 연동 — 박스오피스 TOP 10 실데이터
3. ✅ KOBIS 실시간 예매율 스크래퍼 — 실시간 예매율 TOP 10
4. 🔄 4사 프로모션 크롤러 — 롯데·메가박스 완료, CGV 보류 (현재)
5. ⏭ 정적 DB(SQLite) 저장 + 일배치
6. ⏭ 시계열 분석 (Pre/Post uplift)

## 라이선스

내부용. 외부 공개 시 라이선스 명시 필요.
