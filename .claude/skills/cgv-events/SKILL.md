---
name: cgv-events
description: CGV 이벤트/혜택 페이지에서 진행중 이벤트(쿠폰·무대인사·시사회·GV·굿즈)를 Selenium 으로 수집하고 포스터 이미지를 다운로드한 뒤, 무대인사·시사회·GV 일정표(지점·관·회차→좌석)와 굿즈 대상극장(진행관수)을 LLM 이 직접 판독하고, 판매 단품은 제외해 promotions_cgv.json 에 정리한다. 트리거 - "CGV 이벤트 수집", "CGV 무대인사 분석", "CGV 굿즈 진행관수", "CGV 새 이벤트", "/cgv-events", "CGV 포스터 분석".
---

# CGV 이벤트 수집 + 일정·굿즈 판독

CGV 이벤트 API(`searchEvtListForPage`)는 x-signature HMAC 서명을 요구해 외부 직접 호출 불가. 따라서:

1. **Selenium + CDP** 로 진짜 브라우저를 띄워 CGV 이벤트/혜택 페이지를 순회하면 CGV JS 가 서명·호출한 응답을 캡처
2. 진행중 이벤트(`expnYn=N`) 메타 + 포스터 이미지 다운로드
3. 무대인사·시사회·GV(stage) 회차 → **`fetch_cgv_booking.py` 가 부킹 API 로 자동 검출** (TOP10 영화 × 이벤트 기간 × 지역 사이트 스캔, `searchSchByMov` 응답에서 `prodNm` 에 박힌 "(프리미어 상영)"/"(GV)"/"(무대인사)" 마커로 식별). 결과는 `assets/data/cgv_auto_screenings.json` → build 가 자동 머지
4. 자동검출 못 잡는 케이스(부킹 미노출·매진 종료·특수관 미명시·prodNm 마커 불일치)는 **포스터 LLM 판독으로 `SCREENINGS` 수동 추가**(수동 우선)
5. 굿즈·특전 포스터 → **대상 극장 목록(진행관수)** 판독 → `GOODS_THEATERS`
6. **판매 단품**(키링·쿠지 등 유료 상품) 식별 → `SALE_EVENTS` (대시보드·집계 제외)
7. `scripts/build_promotions_cgv.py` 의 dict 갱신 후 빌더 재실행 → `promotions_cgv.json`

> **4종 dict 모두 `scripts/build_promotions_cgv.py` 상단에 있음**
> - `SCREENINGS` = 무대인사 evntNo → [{branch, hall, sessions}] (수동, 우선 적용)
> - `GOODS_THEATERS` = 굿즈 evntNo → 진행관수(정수)
> - `COUPON_COUNTS` = 쿠폰 발행수 수동 오버라이드(평소 비움 · 크롤러가 자동 추출)
> - `SALE_EVENTS` = 판매 단품 evntNo set (완전 제외)
>
> **자동검출 산출**: `assets/data/cgv_auto_screenings.json`
> = {evntNo: [{branch, hall, sessions, seats}]} — `fetch_cgv_booking.py` 가 매 일일
> 배치마다 갱신. build 가 auto 우선(seats>0 인 경우), 아니면 manual SCREENINGS
> fallback. auto 매칭된 이벤트엔 `autoDetected: true` 플래그.
>
> **최대 누적 (union)**: 시점별 부킹 매진/숨김으로 회차 사라지는 회귀 방지 — 동일
> (evntNo, branch, hall) 의 max(sessions, seats) 보존. 한 번이라도 잡힌 회차는
> 영구 유지(evntNo 종료되면 build 가 endedEvents 로 보내며 집계 자동 제외).

## 절차

### 1단계: 이미지 수집 (필요 시)
이미 오늘 돌렸으면 스킵. 진행:

```bash
python scripts/fetch_cgv_images.py
```

산출물:
- `assets/data/cgv_images/{evntNo}.jpg` — 이벤트 상세 포스터
- `assets/data/cgv_images/_pending.json` — evntNo·title·기간·이미지경로 메타

크롤러는 5개 roundtab(영화·SPECIAL·극장·제휴·멤버십/CLUB) × 영화 하위 sub-sub-tab(전체/일반/시사회/무대인사/아트하우스) 까지 순회해 전체 이벤트(약 130~160건)를 잡는다. CDP `Network.getResponseBody` 로 `searchEvtListForPage` 응답을 캡처.

### 2단계: 신규 분석 대상 식별
`_pending.json` 이벤트 중 `[영화명]` 이 `booking.json` 의 `bookingRate` TOP 10 과
매칭되고, 아직 dict 에 없는 것만 분석:
- **무대인사·시사회·GV** (키워드: 무대인사·시사회·GV·관객과의대화) → `SCREENINGS` 미등록분
- **굿즈·특전** (포스터/TTT/증정/아트카드/굿즈패키지 등) → `GOODS_THEATERS` 미등록분
- **쿠폰** (쿠폰/할인/관람권) → 이미지에 발행수 명시되면 `COUPON_COUNTS`
- **판매 의심** (키링/쿠지/드링크 "출시·단품·N,NNN원") → 이미지로 판매 확인 후 `SALE_EVENTS`

CGV 브랜드명의 `GV` 가 무대인사 키워드로 오인되지 않도록 분류 시 `name.replace("CGV", "")` 후 검색.

### 3단계: 포스터 이미지 판독 (핵심)
`Read` 툴로 `assets/data/cgv_images/{evntNo}.jpg` 를 직접 열어 일정표를 추출. 포스터가 780×3000+ px 로 길어서 한 번에 못 읽으면 **PIL 로 crop** 해서 조각별로 본다:

```python
from PIL import Image
im = Image.open("assets/data/cgv_images/202605117840.jpg")
im.crop((0, 700, 780, 1500)).save("assets/data/cgv_images/_crop_XXX.jpg", quality=92)
```

일정표 표 구조 (CGV 표준):

| 날짜 | 극장 | 상영관 | 상영시간 | 무대인사 | 참석자 |
|------|------|--------|----------|----------|--------|
| 5/30(토) | CGV 영등포 | IMAX | 15:20 | 상영 후 | ... |
| | | 1 | 15:30 | 상영 후 | ... |
| | CGV 용산아이파크몰 | IMAX | 16:45 | 상영 후 | ... |

추출 결과 → `{branch, hall, sessions}` 리스트. **관이 명시 안 된 시사회/GV는 hall=None**(빌더가 지점 평균 좌석 사용).

### 4단계: SCREENINGS dict 갱신
`scripts/build_promotions_cgv.py` 의 상단 `SCREENINGS` dict 에 추가:

```python
SCREENINGS = {
    # ... 기존 ...
    "202605117840": [  # [군체] 개봉 2주차 무대인사
        {"branch": "영등포", "hall": "12관", "sessions": 2},  # IMAX LASER
        {"branch": "영등포", "hall": "1관", "sessions": 2},
        {"branch": "용산아이파크몰", "hall": "20관", "sessions": 2},  # IMAX LASER
        {"branch": "용산아이파크몰", "hall": "15관", "sessions": 2},
        {"branch": "용산아이파크몰", "hall": "13관", "sessions": 1},
    ],
}
```

**hall 표기:**
- 포스터에서 `IMAX` 라고만 쓰여 있어도 실제 관 번호로 매핑 (영등포 12관 IMAX LASER, 용산 20관 IMAX LASER 등) — `theater_seats_cgv.json` 의 type 필드 참고
- 포스터에서 `1` 만 표시되면 `"1관"` 으로
- `Dolby Cinema`, `SCREENX` 같은 특수관도 그대로 적되, theater_seats 에 매칭 안 되면 빌더가 지점 평균으로 fallback

### 5단계: 굿즈 진행관수 판독 → GOODS_THEATERS
굿즈·특전 포스터(`{evntNo}.jpg`)의 **"대상 극장" / "진행 극장"** 영역을 판독해
지점 수를 센다. 보통 이미지 하단(y 42%~) 에 있어 PIL crop 권장:

```python
im = Image.open("assets/data/cgv_images/202605187848.jpg")
im.crop((0, int(im.height*0.42), 780, im.height)).save("_g.jpg", quality=88)
```

예: `[군체] 4DX 포스터 증정` → "대상 극장: 강변, 계양, … 평택" = **37개**. 4DX/IMAX/
SCREENX 포스터는 해당 특수관 보유 지점만이라 수가 다르다 (4DX 37 · IMAX 27 · SCREENX 24 등).

`scripts/build_promotions_cgv.py` 의 `GOODS_THEATERS` 에 추가:
```python
GOODS_THEATERS = {
    # ... 기존 ...
    "202605187848": 37,   # [군체] 4DX 포스터 증정
}
```
- 진행 극장 목록이 없고 "전점"·"광음시네마 보유 지점" 처럼 수가 불명확하면 dict 에
  넣지 말 것 → 빌더가 자동으로 "미공개" 표기.

### 6단계: 판매 단품 제외 → SALE_EVENTS
굿즈 중 **증정이 아니라 돈 주고 사는 단품**(키링·쿠지·드링크 등, 이미지에 가격
"N,NNN원" 표기)은 프로모션 집계 의미가 없으므로 제외. evntNo 를 `SALE_EVENTS` 에 추가:
```python
SALE_EVENTS = {
    "202604237123",   # [악마는 프라다2] 키링 출시 (단품 8,500원)
}
```
- **포함 예외**: 유료 굿즈패키지(특별 상영회 티켓값에 굿즈 포함, 예: 너바나 17,000원
  케이블)는 **관람객 증정**이라 포함 (SALE 아님).
- 빌더가 `SALE_EVENTS` 의 evntNo 를 events·counts 에서 완전히 스킵.

### 6.5단계: 쿠폰 발행수 (자동 추출)
**서프라이즈 쿠폰 등 수량 한정 쿠폰은 크롤러가 자동으로 발행수를 등록한다.**
CGV 쿠폰 상세페이지에는 발행수가 **이미지가 아니라 본문 텍스트(DOM)** 의
"쿠폰 사용수량" 위젯에 있다:

```
쿠폰 사용수량
100%
4,000소진
START
4,000명     ← 총 발행량 = 4,000매
```

- `fetch_cgv_images.py` 의 `extract_coupon_issued()` 가 상세 본문 innerText 에서
  `쿠폰 사용수량` 앵커 뒤의 `N명`(START 뒤 총량)을 파싱 → `_pending.json` 의
  `couponIssued` 로 저장 → 빌더가 coupon 이벤트의 `issued` 로 등록.
- 정부지원·상시 할인쿠폰은 위젯이 없어 자동으로 미공개 처리(None).
- **이미지 판독 불필요** — 텍스트라 매일 자동 수집됨. (검증: 호빵맨 서프라이즈
  4,000 · 남태령 2,500 · 교생실습 4,000 모두 정상 추출)

**수동 오버라이드**(`COUPON_COUNTS`): 자동 추출이 틀린 경우에만 evntNo→발행수로
강제. 평소엔 비워둔다. (오버라이드가 자동값보다 우선)
```python
COUPON_COUNTS = {
    # "202605XXXXXX": 300,   # 자동 추출이 틀릴 때만 수동 지정
}
```

### 7단계: 빌드 + 검증
```bash
python scripts/build_promotions_cgv.py
```

출력 예시:
```
영화별 promoSeats:
  군체                  7,206 석  (stage=3·goods=3·...)
  와일드 씽             5,543 석  (stage=2·goods=0·...)
  ...
```

대시보드 매트릭스(섹션 03) "프로모션 좌석" + 영화별 모달의 무대인사 좌석·굿즈
진행관수가 자동 갱신됨. 모달은 `assets/js/dashboard.js` 의 `buildPromoDetail()`
(stage→seats·goods→theaters·sale 자동 제외) 가 렌더.

## 좌석 DB 보완 (placeholder → 진짜)
`theater_seats_cgv.json` 의 일부 지점은 가짜(placeholder) 좌석. 나무위키에서 실제
관별 좌석을 긁어 채운다:
```bash
python scripts/scrape_cgv_seats.py   # placeholder 지점만 나무위키 'CGV {지점}' 파싱
```
- 현재 160/195 진짜. 남은 placeholder 는 나무위키 페이지 없음(404·폐점) 또는 관별
  좌석 미작성(요약만) 이라 추가 추출 불가 — 단 무대인사 진행 지점은 전부 진짜라 영향 없음.
- 파서는 3형식 지원(`N관: NNN석`·`N관 - NNN석`·`N관 … 총 NNN석`) + 전체 텍스트 파싱
  (페이지 상단 접기 토글의 '둘러보기' 에서 자르면 본문 누락되므로 컷 안 함).

## 핵심 파일
- 크롤러: `scripts/fetch_cgv_images.py` — Selenium + CDP, sub-sub-tab 순회
- 빌더: `scripts/build_promotions_cgv.py` — `SCREENINGS`·`GOODS_THEATERS`·`SALE_EVENTS`
  dict + `_pending.json` + `theater_seats_cgv.json` 조립
- 좌석 스크래퍼: `scripts/scrape_cgv_seats.py` — 나무위키 placeholder 보완
- 좌석 DB: `assets/data/theater_seats_cgv.json` — 160/195 진짜
- 이미지: `assets/data/cgv_images/{evntNo}.jpg` · 메타: `_pending.json`
- 결과: `assets/data/promotions_cgv.json`

## 주의
- 영화 매칭은 **booking.json TOP 10 한정** (boxoffice 섞지 말 것 — 짱구·왕과사는남자 등 leak)
- 종료 1개월 이상 지난 이벤트는 자동 제외 (크롤러가 expnYn=N 필터)
- 포스터 못 받은 이벤트(`/mShrtU/XXXXX` 단축 URL·제휴/멤버십 카드)는 분석 불필요 — name-only 분류만
- 굿즈 진행관수·SALE 은 **booking TOP 10 매칭 굿즈만** 판독 (범위 한정)
- 저장은 집계 수준(좌석 합·진행관 수). 상영 시간·참석자·진행 지점 이름 목록은 JSON 에
  안 담음 — 필요하면 스키마 확장
