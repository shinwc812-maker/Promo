---
name: lotte-events
description: 롯데시네마 LCWS API (EventData.aspx + GetStageGreetingEventDetailTOBE) 를 호출해 이벤트 목록 + 무대인사·시사회 회차별 일정(지점·관·시간·MovieNameKR)을 직접 받아 promotions_lotte.json 의 promoSeats 를 자동 합산한다. 이미지 판독 불필요. 트리거 - "롯데 이벤트 수집", "롯데시네마 무대인사", "Lotte 갱신", "/lotte-events".
---

# 롯데시네마 이벤트 수집 + API 일정 추출

롯데는 **이미지 판독이 필요 없다.** LCWS API 가 회차별 지점·관·시간을 JSON 으로 직접 제공하기 때문.

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

## 핵심 파일

- 크롤러: `scripts/fetch_promotions_lotte.py` — 표준 lib 만 (urllib + json), API 직접
- 좌석 DB: `assets/data/theater_seats_lotte.json` — 61 지점 진짜 데이터
- 이미지: `assets/data/lotte_images/{EventID}.jpg` — 보조 (판독 안 함, 보고용 보관)
- 결과: `assets/data/promotions_lotte.json`

## 주의

- LCWS API 는 쿠키 + Referer 필수 — 없으면 `NullReference` 에러
- multipart form-data 로 `paramList` 전송 (JSON 그대로 일 때 정상)
- `MethodName` 오타 시 `요청하신 서비스명이 존재하지 않습니다` — 정확히 `GetStageGreetingEventDetailTOBE`
- 영화명은 **MovieNameKR** 가 정답. `<영화명>` 이벤트명 파싱은 fallback (오기·생략 가능)
- 시사회(EventTypeCode=108) 일부는 Items 비어있음 → seats=0 으로 저장 (등록만)
- API 가 일정을 직접 주므로 **이미지 판독 작업 자체가 불필요**

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
