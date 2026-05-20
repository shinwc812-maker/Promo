---
name: lotte-events
description: 롯데시네마 LCWS API (EventData.aspx + GetStageGreetingEventDetailTOBE) 로 무대인사·시사회 회차별 일정(지점·관·시간·MovieNameKR)을 자동 받아 promoSeats 를 합산하고, 굿즈 상세 포스터(EventTemplateInfo)에서 진행관수를 판독하며 판매 단품은 제외해 promotions_lotte.json 에 정리한다. 트리거 - "롯데 이벤트 수집", "롯데시네마 무대인사", "롯데 굿즈 진행관수", "Lotte 갱신", "/lotte-events".
---

# 롯데시네마 이벤트 수집 + API 일정 + 굿즈 판독

롯데는 **무대인사·시사회는 이미지 판독 불필요** (API 가 회차별 지점·관·시간을 직접
제공). **굿즈 진행관수만 상세 포스터를 판독**한다.

- `SCREENINGS` 없음 (stage 는 API 자동) — `fetch_promotions_lotte.py` 상단에
  `GOODS_THEATERS`(굿즈 evntNo→진행관수) · `COUPON_COUNTS`(쿠폰 발행수 수동
  오버라이드 — 무비싸다구 등은 EventCntnt '선착순 N명' 자동 추출) ·
  `SALE_EVENTS`(판매 단품 제외) dict 를 둠.

## 핵심 API

### GetEventLists (이벤트 목록)
```
POST https://www.lottecinema.co.kr/LCWS/Event/EventData.aspx
paramList: {
  "MethodName": "GetEventLists",
  "EventClassificationCode": "10|20|40",  // 10=쿠폰 20=굿즈 40=무대인사·시사회
  "PageSize": 100, "PageNo": 1, ...
}
```
세션 쿠키 + Referer(`/NLCHS/Event`) 필요. 응답: `Items[]` 에 `EventID·EventName·EventTypeCode·ProgressStartDate·ProgressEndDate·ImageUrl(썸네일)·EventTypeName`.

`EventTypeCode`:
- `107` = 무대인사
- `108` = 시사회

### GetStageGreetingEventDetailTOBE (회차 상세) ← **핵심**
```
POST https://www.lottecinema.co.kr/LCWS/Event/EventData.aspx
paramList: {
  "MethodName": "GetStageGreetingEventDetailTOBE",
  "EventID": "401070016926158", ...
}
```

응답:
```json
{
  "StageGreetingEventDetail": [{
    "ImgUrl": "http://cf.lottecinema.co.kr/Media/Event/XXX.jpg",  // 980x5830 큰 포스터
    "Items": [{
      "EventID": "401070016926158",
      "PlayDate": "2026-05-23",
      "CinemaName": "건대입구",
      "ScreenName": "2관",
      "StartTime": "16:00",
      "MovieNameKR": "신극장판 은혼: 요시와라 대염상",
      "RemainingSeatCount": 125, ...
    }, ...]
  }]
}
```

**Items 배열의 각 원소가 한 회차 = 한 줄.** 같은 지점·관 끼리 묶어 sessions 카운트.

무대인사(107) · 시사회(108) 모두 같은 method 사용. 응모형 시사회는 Items 가 비어있을 수 있음(회차 미정).

## 절차 — 한 번에 끝남

```bash
python scripts/fetch_promotions_lotte.py
```

스크립트가 자동으로:
1. ECC=10·20·40 이벤트 전부 수집
2. 30일 이상 지난 이벤트 cutoff 제외
3. 분류 (coupon/stage/goods/etc) — 이벤트명 키워드 + ECC 코드 결합
4. **stage 이벤트마다 `GetStageGreetingEventDetailTOBE` 추가 호출** → Items 에서 회차 추출
5. `theater_seats_lotte.json` (61지점, placeholder 없는 진짜 데이터) 조회 → 회차×관좌석 합산
6. `ImgUrl` 큰 포스터를 `assets/data/lotte_images/{EventID}.jpg` 에 다운로드 (이미 있으면 skip)
7. 영화 매칭: **Items[].MovieNameKR 우선**(가장 정확), 다음 이벤트명 `<영화명>` 파싱 — 모두 booking.json TOP 10 한정
8. `promotions_lotte.json` 저장 — `events[].screenings[]`, `events[].seats`, `movies[].promoSeats`

출력:
```
✓ 롯데 프로모션 저장 → assets\data\promotions_lotte.json
  진행 이벤트 79건 · 영화 매칭 7편 · 미매칭 59건 · 포스터 이미지 12건 신규 저장
  영화별 promoSeats:
    군체           3,428 석  (stage=2)
    와일드 씽       5,839 석  (stage=1)
    ...
```

## 굿즈 진행관수 판독 → GOODS_THEATERS
무대인사와 달리 굿즈(ECC=20)는 API 가 회차를 안 줘서 **상세 포스터를 판독**한다.
굿즈 상세 페이지는 **`EventTemplateInfo`** 템플릿 (무대인사의 StageGreeting 과 다름):

1. 굿즈 이벤트 상세 포스터 URL 얻기 — Selenium 으로 페이지 열어 `Media/Event` 큰
   이미지(naturalHeight≥800) src 추출:
   ```
   https://www.lottecinema.co.kr/NLCHS/Event/EventTemplateInfo?eventId={EventID}
   ```
2. 포스터(`cf.lottecinema.co.kr/Media/Event/{guid}.jpg`, 980×5000+) 다운로드 후
   **"진행 극장" 영역** 판독 → 지점 수 카운트
   - 예: `<마이클> 시그니처 아트카드` → 서울 16+경기 17+… = **59개** (전국)
   - `<악마는프라다2> 4주차 증정` → 15개
   - "광음시네마 보유 지점" 처럼 목록 미명시면 dict 에 안 넣음 → 미공개
3. `GOODS_THEATERS` 에 추가 (키는 문자열 EventID):
   ```python
   GOODS_THEATERS = {
       "201010016926397": 59,   # 군체 시그니처 아트카드 (전국)
       "201010016926402": 15,   # 악마는프라다2 4주차 증정
   }
   ```

## 쿠폰 발행수 (자동 추출)
**무비싸다구 등 선착순 쿠폰의 발행수는 크롤러가 자동 등록한다.** 발행수는 이벤트
본문 `EventCntnt`(+`EventNtc`) 텍스트의 "선착순 N명"(또는 N매/N장)에 있어,
`extract_coupon_issued()` 가 파싱해 coupon 이벤트의 `issued` 로 넣는다. 정부지원·
1+1 등 수량 없는 쿠폰은 자동으로 미공개(None).
- 수동 오버라이드(`COUPON_COUNTS`): 자동값이 틀릴 때만 EventID→발행수 지정.
- ⚠ **무비싸다구는 모바일에서 노출**되고, 비활성 시기엔 이벤트 API(채널 HO/MW/MO·
  ECC 전체·SearchText 검색)에 안 잡힌다(확인 완료). 활성화되면 본문에 "선착순 N명"
  형태로 들어올 것으로 보고 자동 추출하되, 표기가 다르거나 별도 모바일 전용
  엔드포인트라면 활성 시점에 `_COUPON_QTY_PAT`·수집 경로 재확인 필요.

## 판매 단품 제외 → SALE_EVENTS
가격표(원) 붙은 단품 판매(키링·쿠지·드링크)는 `SALE_EVENTS` 에 EventID 추가 →
완전 제외. (유료 굿즈패키지=관람객 증정은 포함.) 현재 롯데 매칭 굿즈엔 판매 단품 없음.

## 핵심 파일

- 크롤러: `scripts/fetch_promotions_lotte.py` — API 직접 + `GOODS_THEATERS`·`SALE_EVENTS` dict
- 좌석 DB: `assets/data/theater_seats_lotte.json` — 61 지점 진짜 데이터 (100%)
- 이미지: `assets/data/lotte_images/{EventID}.jpg` — 무대인사 포스터(API) + 굿즈 포스터(판독용)
- 결과: `assets/data/promotions_lotte.json`

## 주의

- LCWS API 는 쿠키 + Referer 필수 — 없으면 `NullReference` 에러
- multipart form-data 로 `paramList` 전송 (JSON 그대로 일 때 정상)
- `MethodName` 오타 시 `요청하신 서비스명이 존재하지 않습니다` — 정확히 `GetStageGreetingEventDetailTOBE`
- 영화명은 **MovieNameKR** 가 정답. `<영화명>` 이벤트명 파싱은 fallback (오기·생략 가능)
- 시사회(EventTypeCode=108) 일부는 Items 비어있음 → seats=0 으로 저장 (등록만)
- 무대인사·시사회는 API 자동, **굿즈만 EventTemplateInfo 포스터 판독** (booking TOP 10 매칭 굿즈 한정)

## 디버깅

API 응답 확인:
```python
import json
from http.cookiejar import CookieJar
from urllib.request import HTTPCookieProcessor, Request, build_opener

opener = build_opener(HTTPCookieProcessor(CookieJar()))
opener.addheaders = [("User-Agent", "Mozilla/5.0 ...")]
opener.open("https://www.lottecinema.co.kr/NLCHS/Event").read()  # 쿠키 확보

param = {"MethodName": "GetStageGreetingEventDetailTOBE",
         "channelType": "HO", "osType": "PC", "osVersion": "...",
         "EventID": "401070016926158", "MemberNo": "0"}
boundary = "----LotteProbe"
body = (f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="paramList"\r\n\r\n'
        f"{json.dumps(param, ensure_ascii=False)}\r\n"
        f"--{boundary}--\r\n").encode("utf-8")
req = Request("https://www.lottecinema.co.kr/LCWS/Event/EventData.aspx",
              data=body, headers={
    "Content-Type": f"multipart/form-data; boundary={boundary}",
    "Referer": "https://www.lottecinema.co.kr/NLCHS/Event",
    "User-Agent": "..."})
print(json.dumps(json.loads(opener.open(req).read()), ensure_ascii=False, indent=2))
```
