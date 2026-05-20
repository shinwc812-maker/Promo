---
name: cgv-events
description: CGV 이벤트/혜택 페이지에서 진행중 이벤트(쿠폰·무대인사·시사회·GV·굿즈)를 Selenium 으로 수집하고 포스터 이미지를 다운로드한 뒤, 무대인사·시사회·GV 의 일정표를 LLM 이 직접 판독해 지점·관·회차 좌석을 promotions_cgv.json 에 합산한다. 트리거 - "CGV 이벤트 수집", "CGV 무대인사 분석", "CGV 새 이벤트", "/cgv-events", "CGV 포스터 분석".
---

# CGV 이벤트 수집 + 일정 판독

CGV 이벤트 API(`searchEvtListForPage`)는 x-signature HMAC 서명을 요구해 외부 직접 호출 불가. 따라서:

1. **Selenium + CDP** 로 진짜 브라우저를 띄워 CGV 이벤트/혜택 페이지를 순회하면 CGV JS 가 서명·호출한 응답을 캡처
2. 진행중 이벤트(`expnYn=N`) 메타 + 포스터 이미지 다운로드
3. 무대인사·시사회·GV(stage 분류) 포스터에서 **일정표(지점·관·회차)** 를 LLM 이 판독
4. `scripts/build_promotions_cgv.py` 의 `SCREENINGS` dict 에 evntNo → screenings 추가
5. 빌더 재실행 → `promotions_cgv.json` 의 movies[].promoSeats 합산

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

### 2단계: 신규 stage 이벤트 식별
`_pending.json` 의 이벤트 중 다음 조건을 만족하는 것만 분석 대상:
- 이벤트명에 **무대인사·시사회·GV·관객과의대화** 키워드
- `[영화명]` 이 `assets/data/booking.json` 의 `bookingRate` TOP 10 영화와 매칭
- `scripts/build_promotions_cgv.py` 의 `SCREENINGS` dict 에 evntNo 가 **없는 것**(=신규)

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

### 5단계: 빌드 + 검증
```bash
python scripts/build_promotions_cgv.py
```

출력 예시:
```
영화별 promoSeats:
  군체                  7,206 석  (stage=3·goods=3·...)
  와일드 씽             5,532 석  (stage=2·goods=0·...)
  ...
```

대시보드 매트릭스(섹션 03)의 "프로모션 좌석" 컬럼이 자동 갱신됨.

## 핵심 파일

- 크롤러: `scripts/fetch_cgv_images.py` — Selenium + CDP, sub-sub-tab 순회
- 빌더: `scripts/build_promotions_cgv.py` — `SCREENINGS` dict + `_pending.json` + `theater_seats_cgv.json` 조립
- 좌석 DB: `assets/data/theater_seats_cgv.json` — 28 지점 진짜 데이터 + 167 placeholder
- 이미지: `assets/data/cgv_images/{evntNo}.jpg`
- 메타: `assets/data/cgv_images/_pending.json`
- 결과: `assets/data/promotions_cgv.json`

## 주의

- 영화 매칭은 **booking.json TOP 10 한정** (boxoffice 섞지 말 것 — 짱구·왕과사는남자 등 leak)
- 종료 1개월 이상 지난 이벤트는 자동 제외 (크롤러가 expnYn=N 필터)
- 포스터 이미지를 못 받은 이벤트(`/mShrtU/XXXXX` 단축 URL · 제휴/멤버십 카드 등)는 SCREENINGS 분석 불필요 — name-only 분류만
- placeholder 지점(`theater_seats_cgv.json` 의 `"placeholder": true`) 은 좌석 추정치 — 실제 좌석으로 교체 시 promoSeats 정확해짐
