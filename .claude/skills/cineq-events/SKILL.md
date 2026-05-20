---
name: cineq-events
description: 씨네큐 /Event/MoreList API 로 진행중 이벤트 수집 + /Event/Info 정적 HTML 의 file.cineq.co.kr guid 로 본문 이미지를 받아, 무대인사 일정표(지점·관·회차)와 굿즈 진행 극장수를 LLM 이 판독해 SCREENINGS·GOODS_THEATERS dict 갱신, 판매 단품은 SALE_EVENTS 로 제외해 promotions_cineq.json 에 정리. 트리거 - "씨네큐 이벤트", "CineQ 무대인사", "씨네큐 굿즈 진행관수", "씨네큐 갱신", "/cineq-events".
---

# 씨네큐 이벤트 수집 + HTML scrape + 일정·굿즈 판독

씨네큐도 메가박스처럼 **API 는 일정/극장 데이터 안 줘서** 본문 이미지를 LLM 이 판독한다. 상세 HTML 이 정적이라 Selenium 불필요.

`fetch_promotions_cineq.py` 상단 3종 dict:
- `SCREENINGS` = 무대인사 evntNo → [{branch, hall, sessions}]
- `GOODS_THEATERS` = 굿즈 evntNo → 진행관수
- `SALE_EVENTS` = 판매 단품 evntNo set (제외)

## 두 엔드포인트

### /Event/MoreList (이벤트 목록, 페이지네이션)
```
POST https://www.cineq.co.kr/Event/MoreList
form: eventId=0, eventSort=-1
Headers: X-Requested-With: XMLHttpRequest
```
JSON 응답 — 한 배치당 ~12건:
```json
[{
  "EventId": 7078,
  "Title": "<군체> 씨네큐 2주차 무대인사",
  "Duration": "2026.05.30~2026.05.30",
  "Thumb": "https://file.cineq.co.kr/j.aspx?guid=...",
  "Link": "Info?eventId=7078&eventSort=-1"
}, ...]
```

**페이지네이션:** `eventId` 에 배치 마지막 EventId 를 넘기면 그 다음 묶음. 0 시작 → 새 항목 없을 때까지 반복(MAX 50회 안전 상한). 전체 ~450+ 건(과거 이벤트 포함).

### /Event/Info (이벤트 상세 — 일정표 이미지 포함)
```
GET https://www.cineq.co.kr/Event/Info?eventId=7078
```
**정적 HTML 안에 file.cineq.co.kr guid 3개 직접 포함** (Selenium 안 써도 됨):
```python
re.findall(r'guid=([a-f0-9]{32})', html)
# → ['1898d605...', '5c94e37d...', 'c546d022...']
```

이미지 GUID 패턴 (순서):
- `_1`: **1020×159** — 시리즈 헤더 (씨네큐 + 제목 띠)
- `_2`: **800×3000~3800** — 본문 큰 포스터 (**일정표 포함**)
- `_3`: **350×508** — 정사각 썸네일

이미지 URL: `https://file.cineq.co.kr/j.aspx?guid={GUID}`

## 절차

### 1단계: 자동 수집 + 본문 이미지 다운로드
```bash
python scripts/fetch_promotions_cineq.py
```

스크립트가 자동으로:
1. MoreList 끝까지 페이징 (~450건)
2. **30일 종료 cutoff 필터** — 이벤트 Duration 끝값 비교
3. 분류 (coupon/stage/goods/etc) — 이벤트명 키워드
4. **stage 이벤트마다 Info HTML 받고 guid 3장 다운로드** → `cineq_images/{eid}_1.jpg`·`_2.jpg`·`_3.jpg`
5. `SCREENINGS` dict 있으면 좌석 합산
6. 영화 매칭(booking.json TOP 10) 후 `promotions_cineq.json` 저장

### 2단계: 새 stage 이벤트의 일정표 판독
**일정표 = `cineq_images/{eid}_2.jpg`** (800×3000+ 본문). 다른 _1/_3 은 헤더/썸네일이라 판독 불필요.

`_2.jpg` 가 길어서 한 번에 못 읽을 수 있음 → PIL 로 일정표 부분만 crop:

```python
from PIL import Image
im = Image.open("assets/data/cineq_images/7078_2.jpg")
# 일정표는 보통 1500~2400 사이 (영화 로고 → 표 → 보도스틸 순)
im.crop((0, 1000, 800, 2400)).save("_crop.jpg", quality=92)
```

표 구조 (CineQ 표준 — CGV 와 거의 동일):

| 날짜 | 극장 | 상영관 | 상영시간 | 무대인사 | 참석자 |
|------|------|--------|----------|----------|--------|
| 5/30(토) | 씨네큐 신도림 | 1 | 14:15 | 상영 후 | ... |
| | | 2 | 14:25 | 상영 후 | |
| | | 1 | 16:50 | 상영 전 | |

추출 → `{branch, hall, sessions}` 리스트. **회원시사회 처럼 관 미명시면 hall=None.**

### 3단계: SCREENINGS dict 갱신
`scripts/fetch_promotions_cineq.py` 의 상단:

```python
SCREENINGS = {
    # ... 기존 ...
    "7078": [  # 군체 2주차 무대인사
        {"branch": "신도림", "hall": "1관", "sessions": 2},
        {"branch": "신도림", "hall": "2관", "sessions": 1},
    ],
    "6996": [  # 마이클 회원시사회 (관 미명시)
        {"branch": "신도림", "hall": None, "sessions": 1},
    ],
}
```

**hall 표기:**
- 포스터에서 숫자만 표시 → `"1관"` 형태로
- 관 미명시(회원시사 등) → `hall=None` (빌더가 신도림 평균 ~114석 사용)

### 4단계: 굿즈 진행관수 → GOODS_THEATERS
굿즈 이벤트도 stage 와 동일하게 guid 3장 다운로드됨. **`_2.jpg`(본문)** 의 "진행
극장" 영역 판독 → 지점 수. (씨네큐는 지점이 8개뿐이라 보통 1~5개)
- 예: `<신극장판 은혼> 개봉주 주말 현장 증정` → 경주보문·구미봉곡·남양주다산·신도림·청라 = **5개**
- `<너바나> 개봉 1주차 현장 증정` → 신도림 = **1개**
```python
GOODS_THEATERS = {
    "7136": 5,   # 신극장판 은혼 개봉주 주말 현장 증정
    "7091": 1,   # 너바나 개봉 1주차 현장 증정
    "6922": 3,   # 악마는프라다2 개봉주 스페셜 포스터
}
```
> 굿즈는 stage 가 아니라 분류상 fetch 시 이미지 다운로드가 안 될 수 있음 — 그 경우
> Info HTML 의 guid 를 직접 받아(디버깅 코드 참고) 판독.

### 5단계: 판매 단품 제외 → SALE_EVENTS
가격(원) 붙은 단품 판매는 `SALE_EVENTS` 에 추가. 현재 씨네큐 매칭 굿즈엔 판매 단품 없음(`set()`).

### 6단계: 재실행 → 좌석·진행관수 합산
```bash
python scripts/fetch_promotions_cineq.py
```
이미지 이미 받아둔 거 skip, dict 변경분만 반영.

## 핵심 파일

- 크롤러: `scripts/fetch_promotions_cineq.py` — `SCREENINGS`·`GOODS_THEATERS`·`SALE_EVENTS` dict
- 좌석 DB: `assets/data/theater_seats_cineq.json` — 8 지점 100% 진짜 (신도림 1관 214 등)
- 이미지: `assets/data/cineq_images/{eid}_{1,2,3}.jpg`
- 결과: `assets/data/promotions_cineq.json`

## 주의

- MoreList 페이지네이션 안 하면 12건만 잡힘 (전 버전 버그) — `eventId=last_id` 로 끝까지 돌릴 것
- 이벤트 본문 GUID 는 정적 HTML 에 직접 있어 Selenium 불필요 — `re.findall(r'guid=([a-f0-9]{32})', html)` 로 추출
- **각 이벤트당 GUID 3개씩** 순서 보존 (`dict.fromkeys` trick) — `_1`(헤더)·`_2`(본문)·`_3`(썸네일)
- 영화 매칭은 booking.json TOP 10 한정
- 회원시사회는 보통 1지점·1회·관 미명시 → hall=None
- 신도림 외 지점(경주보문·구미봉곡·인천청라·남양주다산·해운대장산·고양원당 등) 에 무대인사 진행되는 경우는 드물지만 `theater_seats_cineq.json` 에 다 있어 모두 합산 가능

## 디버깅

특정 이벤트의 GUID + 이미지 확인:
```python
import re
from urllib.request import Request, urlopen

UA = "Mozilla/5.0 ..."
html = urlopen(Request("https://www.cineq.co.kr/Event/Info?eventId=7078",
              headers={"User-Agent": UA}), timeout=15).read().decode("utf-8", "replace")
guids = list(dict.fromkeys(re.findall(r'guid=([a-f0-9]{32})', html)))
for i, g in enumerate(guids, 1):
    print(f"_{i}: https://file.cineq.co.kr/j.aspx?guid={g}")
```
