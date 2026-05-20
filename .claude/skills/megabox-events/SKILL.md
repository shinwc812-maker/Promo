---
name: megabox-events
description: 메가박스 eventMngDiv.do 로 진행중 이벤트 목록 + event/detail HTML scrape 로 본문 editorImg 이미지를 받아, 무대인사 일정표(지점·관·회차)와 굿즈 진행 극장수를 LLM 이 판독해 SCREENINGS·GOODS_THEATERS dict 갱신, 판매 단품은 SALE_EVENTS 로 제외해 promotions_megabox.json 에 정리. 트리거 - "메가박스 이벤트", "Megabox 무대인사", "메가박스 굿즈 진행관수", "메가박스 갱신", "/megabox-events".
---

# 메가박스 이벤트 수집 + HTML scrape + 일정·굿즈 판독

메가박스는 **API 가 일정/극장 데이터를 따로 안 줘서** 본문 이미지를 LLM 이 판독한다. 상세 페이지가 정적 HTML 이라 Selenium 불필요.

`fetch_promotions_megabox.py` 상단 4종 dict:
- `SCREENINGS` = 무대인사 evntNo → [{branch, hall, sessions}]
- `GOODS_THEATERS` = 굿즈 evntNo → 진행관수
- `COUPON_COUNTS` = 쿠폰 evntNo → 발행수 (총 N장·선착순 N명 명시된 경우만)
- `SALE_EVENTS` = 판매 단품 evntNo set (제외)

## 두 API/엔드포인트

### eventMngDiv.do (이벤트 목록)
```
POST https://www.megabox.co.kr/on/oh/ohe/Event/eventMngDiv.do
form: currentPage=1, eventStatCd=ONG  // ONG = 진행중
Headers: X-Requested-With: XMLHttpRequest, Referer: /event
```
응답은 **HTML fragment** (서버 렌더링). 카드 형식:
```html
<a class="eventBtn" data-no="20591" href="#">
  <p class="tit">&lt;와일드 씽&gt; 개봉주 무대인사</p>
  <p class="date">2026.06.06 ~ 2026.06.07</p>
</a>
```

페이지네이션: currentPage 증가시키며 새 항목 없을 때까지 (MAX_PAGES=30 안전 상한). `data-no` 가 EventID.

### event/detail (이벤트 상세 — 일정표 이미지 포함)
```
GET https://www.megabox.co.kr/event/detail?eventNo=20591
```
정적 HTML (96KB+). `<div class="event-detail">` 안에 본문 이미지들:
```html
<img src="\SharedImg\editorImg\2026\05\13\ZWQjcYiTAFUezryMEFM6rpZV8NmptvYs.jpg">
```
**backslash 인코딩** (`\SharedImg\editorImg\...`) — `re.findall` 시 raw string 의 `\` 가 regex `\e` 오류 일으키므로 `html.replace("\\", "/")` 후 매칭:
```python
PAT = re.compile(r'src="(/?SharedImg/editorImg/[^"]+\.(?:jpg|png|gif))"')
section = html[pos:].replace("\\", "/")
paths = PAT.findall(section)
urls = ["https://img.megabox.co.kr" + (p if p.startswith("/") else "/"+p) for p in paths]
```

이벤트마다 본문 이미지 4~6장 (헤더 → 무대인사 정보 → 일정표 → 영화 정보 → 유의사항). **일정표는 보통 2~3번째 이미지.**

## 절차

### 1단계: 자동 수집 + 본문 이미지 다운로드
```bash
python scripts/fetch_promotions_megabox.py
```

스크립트가 자동으로:
1. eventMngDiv.do 페이징해서 진행중 이벤트 전부 수집
2. 분류 (coupon/stage/goods/etc) — 이벤트명 키워드
3. **stage 이벤트마다 event/detail HTML 받고 본문 editorImg 모두 다운로드** → `megabox_images/{eid}_{n}.jpg`
4. `SCREENINGS` dict 에 evntNo 있으면 좌석 합산
5. 영화 매칭(booking.json TOP 10) 후 `promotions_megabox.json` 저장

### 2단계: 새 stage 이벤트의 일정표 판독
스크립트는 좌석 합산만 자동, **일정표 판독은 LLM 이 수동**:

`megabox_images/{eid}_*.jpg` 들 중 **일정표 이미지 찾기** — 1100×~ 큰 이미지 중 `무대인사 정보` 박스 + 표(날짜·극장·상영관·상영시간·무대인사·참석자) 형태.

표 구조 (메가박스 표준):

| 일정 | 극장 | 상영관 | 상영시간 | 무대인사 | 참석자 |
|------|------|--------|----------|----------|--------|
| 6/6(토) | 코엑스 | Dolby Cinema | 15:20 | 종영 | ... |
| | | 3 | 15:30 | 종영 | |
| 6/7(일) | 상암월드컵경기장 | Dolby Vision Atmos | 10:40 | 종영 | |

추출 → `{branch, hall, sessions}` 리스트.

### 3단계: SCREENINGS dict 갱신
`scripts/fetch_promotions_megabox.py` 의 상단:

```python
SCREENINGS = {
    # ... 기존 ...
    "20591": [  # 와일드 씽 개봉주 무대인사
        {"branch": "코엑스", "hall": "Dolby Cinema", "sessions": 2},
        {"branch": "코엑스", "hall": "3관", "sessions": 2},
        {"branch": "코엑스", "hall": "2관", "sessions": 1},
        {"branch": "상암월드컵경기장", "hall": "Dolby Vision Atmos", "sessions": 2},
        {"branch": "상암월드컵경기장", "hall": "1관", "sessions": 1},
        {"branch": "목동", "hall": "Dolby Vision Atmos", "sessions": 2},
        {"branch": "목동", "hall": "2관", "sessions": 1},
    ],
}
```

**hall 표기 주의:**
- 숫자만 표시되면 `"2관"` 형태로
- `Dolby Cinema`, `Dolby Vision Atmos`, `Dolby Vision+Atmos` 등 특수관 이름은 그대로 — `theater_seats_megabox.json` 에 없으면 빌더가 지점 평균으로 fallback

### 4단계: 굿즈 진행관수 → GOODS_THEATERS
굿즈 이벤트도 본문 editorImg 가 다운로드됨. 그 중 **"진행 극장" 목록** 이미지를
판독해 지점 수를 센다 (작은 글씨면 PIL 로 crop+2배 확대).
- 예: `<내 마음의 위험한 녀석> 개봉주 현장 증정` → 강남·고양스타필드·… = **52개**
```python
GOODS_THEATERS = {
    "20629": 52,   # 내 마음의 위험한 녀석 개봉주 현장 증정
}
```

### 5단계: 판매 단품 제외 → SALE_EVENTS
가격(원) 붙은 단품 판매는 제외. 메가박스는 **쿠지(이치방쿠지)·드링크 콤보**가 흔함:
```python
SALE_EVENTS = {
    "20619",   # 쿠지 단품 11,000원
    "20618",   # 엘리자베스 드링크 25,000원
}
```

### 5.5단계: 쿠폰 발행수 → COUPON_COUNTS
쿠폰 이미지에 "총 N장"·"선착순 N명" 명시되면 `COUPON_COUNTS = {eid: 정수}` (선착순
N명=N장). 수량 없는 "선착순"은 미공개. 대부분 미공개지만 있으면 수집.

### 6단계: 재실행 → 좌석·진행관수 합산
```bash
python scripts/fetch_promotions_megabox.py
```
이미지는 이미 받아둔 거 skip, dict 변경분만 반영.

## 좌석 DB 보완
`theater_seats_megabox.json` 은 원래 가짜(지점 내 모든 관 동일). 나무위키로 보완:
```bash
python scripts/scrape_megabox_seats.py   # 나무위키 '메가박스 {지점}' 파싱
```
현재 69/114 진짜. 무대인사 지점(코엑스·상암·목동)은 진짜. 남은 placeholder 는
나무위키 페이지 없음(404). lookup_seats 는 특수관(Dolby Cinema 등)을 type 필드로 매칭.

## 핵심 파일

- 크롤러: `scripts/fetch_promotions_megabox.py` — `SCREENINGS`·`GOODS_THEATERS`·`SALE_EVENTS` dict
- 좌석 스크래퍼: `scripts/scrape_megabox_seats.py` — 나무위키 보완
- 좌석 DB: `assets/data/theater_seats_megabox.json` — 69/114 진짜
- 이미지: `assets/data/megabox_images/{eid}_{n}.jpg`
- 결과: `assets/data/promotions_megabox.json`

## 주의

- regex backslash 함정: Python 3.14 에서 `\e` 가 invalid escape → **`html.replace("\\", "/")` 로 정규화 후 매칭**
- `<div class="event-detail">` 다음 30000 char 슬라이스만 검색 — 푸터 광고 이미지 잡지 않도록
- 영화 매칭은 booking.json TOP 10 한정
- 시사회는 메가박스에 거의 없음 (대부분 무대인사)
- 본문 이미지가 1~2장이면 보통 헤더만 — 일정표 없는 이벤트 (e.g., 단순 굿즈 행사가 stage 분류된 경우)

## 디버깅

특정 이벤트의 본문 이미지 확인:
```python
import re
from urllib.request import Request, urlopen

UA = "Mozilla/5.0 ..."
html = urlopen(Request("https://www.megabox.co.kr/event/detail?eventNo=20591",
              headers={"User-Agent": UA}), timeout=20).read().decode("utf-8", "replace")
pos = html.find('class="event-detail"')
section = html[pos:pos+30000].replace("\\", "/")
paths = re.findall(r'src="(/?SharedImg/editorImg/[^"]+\.(?:jpg|png|gif))"', section)
for p in paths:
    print("https://img.megabox.co.kr" + (p if p.startswith("/") else "/"+p))
```
