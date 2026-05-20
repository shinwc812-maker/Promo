#!/usr/bin/env python3
"""
fetch_promotions_lotte.py
--------------------------------------------------
롯데시네마 이벤트 API(LCWS/Event/EventData.aspx)를 호출해 영화별
프로모션 현황을 assets/data/promotions_lotte.json 으로 생성한다.

Phase 4(4사 프로모션 크롤러)의 롯데시네마 파일럿. 출력 JSON 스키마는
나머지 체인(CGV·메가박스·씨네큐) 크롤러가 그대로 따를 공통 템플릿이다.

호출 레시피:
  1. 쿠키 자로 이벤트 페이지 GET → 세션 쿠키 확보
     (쿠키·Referer 없으면 API 가 .NET NullReference 에러를 낸다)
  2. EventData.aspx 에 multipart POST (paramList JSON)
  EventClassificationCode: 10=쿠폰/무비싸다구, 20=특전/굿즈, 40=무대인사/시사회

영화 매칭: 이벤트명의 <영화명> 을 파싱해 boxoffice.json / booking.json 의
movieCd 와 조인한다.

의존성: 파이썬 표준 라이브러리만 사용 (pip install · API 키 불필요)
"""
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import HTTPCookieProcessor, Request, build_opener

# Windows 콘솔(cp949)에서 한글 메시지가 깨지지 않도록 출력 인코딩 고정
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

KST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "assets" / "data"
OUT_FILE = DATA_DIR / "promotions_lotte.json"
IMG_DIR = DATA_DIR / "lotte_images"
SEATS_FILE = DATA_DIR / "theater_seats_lotte.json"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
EVENT_PAGE = "https://www.lottecinema.co.kr/NLCHS/Event"
API_URL = "https://www.lottecinema.co.kr/LCWS/Event/EventData.aspx"
CLASS_CODES = ["10", "20", "40"]   # 수집 대상 EventClassificationCode

# 관 매칭 실패 시 사용할 기본 좌석수 (롯데 일반관 평균)
DEFAULT_HALL_SEATS = 150

# 판매 단품(유료) — 증정 아니므로 대시보드·집계 제외 (현재 롯데 매칭 굿즈엔 없음)
SALE_EVENTS = set()

# 쿠폰 발행수 수동 오버라이드. 평소엔 크롤러가 쿠폰의 EventCntnt 본문 '선착순 N명'
# 에서 자동 추출한다. 자동값이 틀릴 때만 EventID → 발행수로 지정.
COUPON_COUNTS = {}

# 무비싸다구 (SpeedMulti 이벤트) — 영화별 쿠폰 발행수를 API 로 자동 수집한다.
# 일반 이벤트 목록(GetEventLists)엔 안 잡히고 전용 메서드 GetSpeedEventDetailMulti
# 로만 조회된다. 새 무비싸다구 배치가 뜨면 그 이벤트 ID 를 아래에 추가/교체.
# 페이지: https://www.lottecinema.co.kr/NLCMW/Event/EventTemplateSpeedMulti?eventId=<ID>
SADAGU_EVENT_IDS = ["201210016922014"]

# 쿠폰(무비싸다구 등) 본문의 '선착순 N명/매/장' 총 발행 수량 패턴
_COUPON_QTY_PAT = re.compile(r"선착순\s*([\d,]+)\s*(?:명|매|장)")


def extract_coupon_issued(ev):
    """이벤트 본문(EventCntnt)+유의사항(EventNtc)에서 '선착순 N명' 추출. 없으면 None."""
    raw = (ev.get("EventCntnt") or "") + " " + (ev.get("EventNtc") or "")
    text = re.sub(r"<[^>]+>", " ", raw).replace("&nbsp;", " ")
    m = _COUPON_QTY_PAT.search(text)
    return int(m.group(1).replace(",", "")) if m else None


def fetch_movie_sadagu(opener):
    """무비싸다구 SpeedMulti 이벤트에서 영화별 쿠폰 발행수를 수집.

    GetSpeedEventDetailMulti 응답 구조:
      SpeedEventDetail[].ItemGroup[](영화별).Items[](쿠폰종류)
        - MovieNm: 영화명 (KOFIC movieCd 아님 → 제목으로 매칭)
        - DisplayCouponName: 할인액(0=0원쿠폰, 2000=2,000원쿠폰)
        - CpnUsableMaxCnt: 총 발행수(매)
    반환: {영화명: [(쿠폰명, 발행수), ...]}
    """
    result = {}
    for eid in SADAGU_EVENT_IDS:
        page = ("https://www.lottecinema.co.kr/NLCMW/Event/"
                f"EventTemplateSpeedMulti?eventId={eid}")
        param = {"MethodName": "GetSpeedEventDetailMulti", "channelType": "MW",
                 "osType": "M", "osVersion": UA, "EventID": "", "MainEventID": eid}
        boundary = "----LotteSadagu"
        body = (f"--{boundary}\r\n"
                'Content-Disposition: form-data; name="paramList"\r\n\r\n'
                f"{json.dumps(param, ensure_ascii=False)}\r\n"
                f"--{boundary}--\r\n").encode("utf-8")
        req = Request(API_URL, data=body, headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Referer": page, "User-Agent": UA})
        try:
            with opener.open(req, timeout=20) as r:
                doc = json.loads(r.read().decode("utf-8"))
        except (HTTPError, URLError, json.JSONDecodeError):
            continue
        if str(doc.get("IsOK")).lower() != "true":
            continue
        for detail in doc.get("SpeedEventDetail") or []:
            for grp in detail.get("ItemGroup") or []:
                for it in grp.get("Items") or []:
                    name = (it.get("MovieNm") or "").strip()
                    issued = it.get("CpnUsableMaxCnt")
                    if not name or not issued:
                        continue
                    try:
                        amt = int(it.get("DisplayCouponName"))
                    except (TypeError, ValueError):
                        amt = None
                    label = ("0원 쿠폰" if amt == 0
                             else (f"{amt:,}원 쿠폰" if amt else "쿠폰"))
                    result.setdefault(name, []).append((label, int(issued)))
    return result

# 굿즈·특전 진행관수 (상세 포스터 '진행 극장' 목록 판독). 미등록은 '미공개'.
# (광음특전처럼 특별관 보유 지점만 표기되고 목록 미명시면 dict 에서 제외 → 미공개)
GOODS_THEATERS = {
    "201010016926397": 59,   # 군체 시그니처 아트카드 (전국)
    "201010016926406": 28,   # 마이클 2주차 주말증정
    "201010016926384": 59,   # 마이클 시그니처 아트카드 (전국)
    "201010016926398": 27,   # 신극장판 은혼 시그니처 아트카드
    "201010016926402": 15,   # 악마는프라다2 4주차 증정
}

# 타입 분류 키워드 (우선순위 순으로 검사)
STAGE_KW = ("무대인사", "GV", "시사회", "관객과의 대화", "관객과의대화")
COUPON_KW = ("무비싸다구", "쿠폰", "관람권", "할인")
GOODS_KW = ("특전", "굿즈", "오브제", "아트카드", "증정", "포토카드")


def classify(name, class_code):
    """이벤트명 + 분류코드로 프로모션 타입 결정."""
    if class_code == "40" or any(k in name for k in STAGE_KW):
        return "stage"
    if any(k in name for k in COUPON_KW):
        return "coupon"
    if any(k in name for k in GOODS_KW):
        return "goods"
    return "etc"


def norm_title(text):
    """매칭용 제목 정규화 — 공백·문장부호 제거 후 소문자화."""
    return re.sub(r"[\s\W_]+", "", text or "").lower()


def fetch_events(opener):
    """ECC 10·20·40 이벤트를 모아 EventID 기준 중복 제거한 리스트 반환."""
    collected = {}
    for code in CLASS_CODES:
        param = {
            "MethodName": "GetEventLists", "channelType": "HO",
            "osType": "PC", "osVersion": UA,
            "EventClassificationCode": code, "SearchText": "",
            "CinemaID": "", "PageNo": 1, "PageSize": 100, "MemberNo": "0",
        }
        boundary = "----lottePromoCrawler"
        body = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="paramList"\r\n\r\n'
            f"{json.dumps(param, ensure_ascii=False)}\r\n"
            f"--{boundary}--\r\n"
        ).encode("utf-8")
        request = Request(API_URL, data=body, headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Referer": EVENT_PAGE, "User-Agent": UA,
        })
        try:
            with opener.open(request, timeout=25) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except (HTTPError, URLError, json.JSONDecodeError) as exc:
            sys.exit(f"롯데 이벤트 API 호출 실패 (ECC={code}): {exc}")
        if str(payload.get("IsOK")).lower() != "true":
            sys.exit(f"롯데 이벤트 API 오류 (ECC={code}): "
                     f"{payload.get('ResultMessage')}")
        for item in payload.get("Items") or []:
            collected[item["EventID"]] = item
    return list(collected.values())


def build_title_map():
    """boxoffice.json + booking.json 으로 norm제목 → (movieCd, 원제목) 맵 구성."""
    title_map = {}
    for fname in ("booking.json",):
        fpath = DATA_DIR / fname
        if not fpath.exists():
            continue
        try:
            doc = json.loads(fpath.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        for row in doc.get("boxOffice") or doc.get("bookingRate") or []:
            if row.get("movieCd") and row.get("title"):
                title_map[norm_title(row["title"])] = (row["movieCd"],
                                                       row["title"])
    return title_map


def build_seat_map():
    """지점·관 → 좌석수 lookup. {지점명: {관명: seats, ...}}"""
    if not SEATS_FILE.exists():
        return {}
    doc = json.loads(SEATS_FILE.read_text(encoding="utf-8"))
    theaters = doc.get("theaters") if isinstance(doc, dict) else doc
    out = {}
    for t in theaters or []:
        out[t.get("name", "")] = {
            (h.get("no") or ""): (h.get("seats") or 0)
            for h in (t.get("halls") or [])
        }
    return out


def fetch_stage_detail(opener, event_id):
    """단일 이벤트 상세 호출 — 회차별 일정(지점·관·시간) + 큰 포스터 ImgUrl 반환.

    무대인사(EventTypeCode=107)와 시사회(108) 모두 같은 method 사용.
    응모형 시사회는 Items 가 비어있을 수 있음.
    """
    param = {"MethodName": "GetStageGreetingEventDetailTOBE",
             "channelType": "HO", "osType": "PC", "osVersion": UA,
             "EventID": event_id, "MemberNo": "0"}
    boundary = "----LotteDetail"
    body = (f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="paramList"\r\n\r\n'
            f"{json.dumps(param, ensure_ascii=False)}\r\n"
            f"--{boundary}--\r\n").encode("utf-8")
    req = Request(API_URL, data=body, headers={
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Referer": EVENT_PAGE, "User-Agent": UA})
    try:
        with opener.open(req, timeout=20) as r:
            p = json.loads(r.read().decode("utf-8"))
    except (HTTPError, URLError, json.JSONDecodeError):
        return None
    if str(p.get("IsOK")).lower() != "true":
        return None
    detail = (p.get("StageGreetingEventDetail") or [{}])[0]
    return {
        "imgUrl": detail.get("ImgUrl") or "",
        "items": detail.get("Items") or [],
    }


def aggregate_screenings(items, seat_map):
    """API Items 를 screenings 배열(지점·관·sessions·seats) 로 압축.

    Items 는 회차 단위(영화별 PlayDate/StartTime 한 줄씩). 같은 지점·관 묶어
    sessions 카운트하고 seats = sessions × 관 좌석수 합산.
    """
    bucket = {}   # (cinema, screen) → {sessions, seats}
    movie_titles = set()
    for it in items:
        cinema = (it.get("CinemaName") or "").strip()
        screen = (it.get("ScreenName") or "").strip()
        movie = (it.get("MovieNameKR") or "").strip()
        if movie:
            movie_titles.add(movie)
        if not cinema or not screen:
            continue
        seats_per = seat_map.get(cinema, {}).get(screen, 0) or DEFAULT_HALL_SEATS
        key = (cinema, screen)
        bucket.setdefault(key, {"sessions": 0, "seats": 0,
                                "seatsPer": seats_per})
        bucket[key]["sessions"] += 1
        bucket[key]["seats"] += seats_per
    screenings = [
        {"branch": c, "hall": s,
         "sessions": v["sessions"], "seats": v["seats"]}
        for (c, s), v in bucket.items()
    ]
    total_seats = sum(s["seats"] for s in screenings)
    return screenings, total_seats, sorted(movie_titles)


def download_image(opener, url, target):
    """포스터 이미지 다운로드 (이미 있으면 스킵)."""
    if not url or target.exists():
        return False
    try:
        with opener.open(Request(url, headers={"User-Agent": UA}),
                         timeout=20) as r:
            blob = r.read()
        target.write_bytes(blob)
        return True
    except (HTTPError, URLError):
        return False


def main():
    opener = build_opener(HTTPCookieProcessor(CookieJar()))
    opener.addheaders = [("User-Agent", UA)]
    # 1) 세션 쿠키 확보
    try:
        opener.open(EVENT_PAGE, timeout=25).read()
    except (HTTPError, URLError) as exc:
        sys.exit(f"롯데 이벤트 페이지 접속 실패: {exc}")

    events = fetch_events(opener)
    if not events:
        sys.exit("수집된 이벤트가 없습니다. (API 구조 변경 가능성)")

    # 종료 1개월 이상 지난 이벤트만 제외 (최근 종료분은 보고에 유지)
    cutoff = (datetime.now(KST) - timedelta(days=30)).strftime("%Y.%m.%d")
    title_map = build_title_map()
    seat_map = build_seat_map()
    IMG_DIR.mkdir(parents=True, exist_ok=True)

    def match_movie(movie_name):
        """정규화 후 동일/부분일치로 movieCd 찾기."""
        norm = norm_title(movie_name)
        if not norm:
            return None
        for key, val in title_map.items():
            if norm == key or norm in key or key in norm:
                return val
        return None

    movies = {}        # movieCd → 영화별 집계 레코드
    unmatched = []
    type_counter = {"coupon": 0, "stage": 0, "goods": 0, "etc": 0}

    images_downloaded = 0
    for ev in events:
        end = ev.get("ProgressEndDate", "")
        if end and end < cutoff:       # 종료 1개월 이상 지난 이벤트만 제외
            continue
        event_id = ev.get("EventID")
        if str(event_id) in SALE_EVENTS:   # 판매 단품 — 대시보드·집계 제외
            continue
        name = (ev.get("EventName") or "").strip()
        ptype = classify(name, ev.get("EventClassificationCode", ""))
        type_counter[ptype] += 1
        event_rec = {
            "eventId": event_id,
            "name": name,
            "type": ptype,
            "start": ev.get("ProgressStartDate", ""),
            "end": end,
        }
        if ptype == "goods" and str(event_id) in GOODS_THEATERS:
            event_rec["theaters"] = GOODS_THEATERS[str(event_id)]
        if ptype == "coupon":
            # 수동 오버라이드 우선, 없으면 EventCntnt '선착순 N명' 자동 추출
            issued = COUPON_COUNTS.get(str(event_id)) or extract_coupon_issued(ev)
            if issued:
                event_rec["issued"] = issued

        # stage 타입: 상세 API 호출 → 회차·지점·좌석 + 큰 포스터 이미지 받기
        stage_movie_titles = []
        if ptype == "stage":
            detail = fetch_stage_detail(opener, str(event_id))
            if detail:
                screenings, total_seats, stage_movie_titles = (
                    aggregate_screenings(detail["items"], seat_map))
                if screenings:
                    event_rec["screenings"] = screenings
                    event_rec["seats"] = total_seats
                    event_rec["branches"] = sorted({s["branch"] for s in screenings})
                if detail["imgUrl"]:
                    event_rec["posterUrl"] = detail["imgUrl"]
                    ext = ".jpg"
                    target = IMG_DIR / f"{event_id}{ext}"
                    if download_image(opener, detail["imgUrl"], target):
                        images_downloaded += 1
                    event_rec["imagePath"] = f"assets/data/lotte_images/{event_id}{ext}"

        # 영화 매칭: 상세 API 의 MovieNameKR 우선, 다음으로 이벤트명 <영화명>
        hit = None
        for cand in stage_movie_titles:
            hit = match_movie(cand)
            if hit:
                break
        if not hit:
            brackets = [b.strip() for b in re.findall(r"<([^<>]+)>", name)]
            for cand in brackets:
                if cand in ("전체", ""):
                    continue
                hit = match_movie(cand)
                if hit:
                    break
        else:
            brackets = []

        if hit:
            movie_cd, title = hit
            rec = movies.setdefault(movie_cd, {
                "movieCd": movie_cd, "title": title, "matched": True,
                "counts": {"coupon": 0, "stage": 0, "goods": 0, "etc": 0},
                "promoSeats": 0,
                "events": [],
            })
            rec["counts"][ptype] += 1
            rec["promoSeats"] += event_rec.get("seats", 0)
            rec["events"].append(event_rec)
        else:
            event_rec["movieName"] = (stage_movie_titles[0] if stage_movie_titles
                                       else (brackets[0] if brackets else None))
            unmatched.append(event_rec)

    # 무비싸다구(SpeedMulti) 주입 — API 로 영화별 발행수 자동 수집 후 TOP10 매칭 주입
    sadagu_data = fetch_movie_sadagu(opener)
    sadagu_injected = 0
    for sad_title, coupons in sadagu_data.items():
        hit = match_movie(sad_title)
        if not hit:                       # TOP10 밖이면 대시보드 미반영 → 스킵
            continue
        movie_cd, mv_title = hit
        rec = movies.setdefault(movie_cd, {
            "movieCd": movie_cd, "title": mv_title, "matched": True,
            "counts": {"coupon": 0, "stage": 0, "goods": 0, "etc": 0},
            "promoSeats": 0, "events": [],
        })
        for idx, (cname, issued) in enumerate(coupons, 1):
            rec["counts"]["coupon"] += 1
            type_counter["coupon"] += 1
            sadagu_injected += 1
            rec["events"].append({
                "eventId": f"sadagu-{movie_cd}-{idx}",
                "name": f"<{mv_title}> 무비싸다구 {cname}",
                "type": "coupon",
                "issued": issued,
                "source": "롯데 무비싸다구 (SpeedMulti API)",
            })

    out = {
        "chain": "LOTTE",
        "source": "롯데시네마 이벤트 API · LCWS/Event/EventData.aspx",
        "fetchedAt": datetime.now(KST).isoformat(timespec="seconds"),
        "movies": sorted(movies.values(),
                         key=lambda m: sum(m["counts"].values()),
                         reverse=True),
        "unmatched": unmatched,
    }
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(out, ensure_ascii=False, indent=2),
                        encoding="utf-8")

    matched_events = sum(len(m["events"]) for m in out["movies"])
    print(f"✓ 롯데 프로모션 저장 → {OUT_FILE.relative_to(ROOT)}")
    print(f"  진행 이벤트 {matched_events + len(unmatched)}건 · "
          f"영화 매칭 {len(out['movies'])}편 · 미매칭 {len(unmatched)}건 · "
          f"포스터 이미지 {images_downloaded}건 신규 저장")
    print(f"  타입 분포: 쿠폰 {type_counter['coupon']} · "
          f"무대인사 {type_counter['stage']} · 굿즈 {type_counter['goods']} · "
          f"기타 {type_counter['etc']}")
    sgu_cpn = sum(len(v) for v in sadagu_data.values())
    if sadagu_data:
        print(f"  무비싸다구: API {len(sadagu_data)}편/{sgu_cpn}쿠폰 · "
              f"TOP10 주입 {sadagu_injected}건")
    else:
        print(f"  ⚠ 무비싸다구 수집 0건 — SADAGU_EVENT_IDS({SADAGU_EVENT_IDS}) "
              f"점검 필요 (이벤트 종료/ID 변경 가능)")
    print("  영화별 promoSeats:")
    for m in out["movies"]:
        if m["promoSeats"] > 0:
            print(f"    {m['title'][:30]:<30s}  {m['promoSeats']:>6,} 석  "
                  f"(stage={m['counts']['stage']})")


if __name__ == "__main__":
    main()
