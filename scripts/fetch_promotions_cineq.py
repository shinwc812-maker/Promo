#!/usr/bin/env python3
"""
fetch_promotions_cineq.py
--------------------------------------------------
씨네큐 이벤트 API(/Event/MoreList)를 호출해 영화별 프로모션
현황을 assets/data/promotions_cineq.json 으로 생성한다.
"""
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import urlencode

# Windows 콘솔(cp949)에서 한글 메시지가 깨지지 않도록 출력 인코딩 고정
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

KST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "assets" / "data"
OUT_FILE = DATA_DIR / "promotions_cineq.json"
IMG_DIR = DATA_DIR / "cineq_images"
SEATS_FILE = DATA_DIR / "theater_seats_cineq.json"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
API_URL = "https://www.cineq.co.kr/Event/MoreList"
DETAIL_URL = "https://www.cineq.co.kr/Event/Info?eventId="
FILE_URL = "https://file.cineq.co.kr/j.aspx?guid="

DEFAULT_HALL_SEATS = 100  # 관 매칭 실패 시 fallback

# 판매 단품(유료) — 증정 아니므로 대시보드·집계 제외 (현재 씨네큐 매칭 굿즈엔 없음)
SALE_EVENTS = set()

# 쿠폰 발행수 — 씨네큐는 발행수가 상세 '이미지' 안 텍스트에 있어(예: '선착순 200명!',
# '한정 15,000건') 자동 텍스트 추출이 불가. 크롤러가 쿠폰 상세 이미지를 받아두면
# LLM 이 판독해 여기 eventId → 발행수(매)로 등록한다. (cineq-events SKILL 참조)
COUPON_COUNTS = {}

# 굿즈·특전 진행관수 (이미지 '진행 극장' 목록 판독). 미등록은 '미공개'.
GOODS_THEATERS = {
    "7136": 5,   # 신극장판 은혼 개봉주 주말 현장 증정
    "7091": 1,   # 너바나 개봉 1주차 현장 증정 (신도림)
    "6922": 3,   # 악마는프라다2 개봉주 스페셜 포스터 (신도림·경주보문·구미봉곡)
}

# 이미지 판독으로 추출한 무대인사·시사회 일정.
# hall=None 이면 관 미명시 → 지점 평균 좌석 사용.
SCREENINGS = {
    # 군체 2주차 무대인사 (5/30 신도림 1관 2회 + 2관 1회)
    "7078": [
        {"branch": "신도림", "hall": "1관", "sessions": 2},
        {"branch": "신도림", "hall": "2관", "sessions": 1},
    ],
    # 마이클 회원시사회 (5/12 신도림 1회 — 관 미명시)
    "6996": [
        {"branch": "신도림", "hall": None, "sessions": 1},
    ],
}

# 타입 분류 키워드
STAGE_KW = ("무대인사", "GV", "시사회", "관객과의 대화", "관객과의대화", "팬미팅")
COUPON_KW = ("쿠폰", "관람권", "할인", "싸다구", "무료", "1+1")
GOODS_KW = ("특전", "굿즈", "포스터", "필름마크", "아트카드", "증정", "배지", "뱃지", "TICKET", "티켓", "경품")


def classify(name):
    """이벤트명 키워드로 프로모션 타입 결정."""
    uname = name.upper()
    if any(k in uname for k in STAGE_KW): return "stage"
    if any(k in uname for k in COUPON_KW): return "coupon"
    if any(k in uname for k in GOODS_KW): return "goods"
    return "etc"


def norm_title(text):
    """매칭용 제목 정규화."""
    return re.sub(r"[\s\W_]+", "", text or "").lower()


def build_title_map():
    """booking.json(실시간 예매율 TOP 10)으로 norm제목 → (movieCd, 원제목) 맵 구성.

    매칭 기준은 '실시간 예매율 TOP 10' 하나로 통일한다. 박스오피스 TOP 10은
    예매율 순위와 달라(짱구·왕과 사는 남자 등), 섞으면 매트릭스 기준이 흐려진다.
    """
    title_map = {}
    for fname in ("booking.json",):
        fpath = DATA_DIR / fname
        if not fpath.exists(): continue
        try:
            doc = json.loads(fpath.read_text(encoding="utf-8"))
            for row in doc.get("boxOffice") or doc.get("bookingRate") or []:
                if row.get("movieCd") and row.get("title"):
                    title_map[norm_title(row["title"])] = (row["movieCd"], row["title"])
        except: continue
    return title_map


def build_seat_map():
    """지점·관 → 좌석수 lookup."""
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


def lookup_seats(seat_map, branch, hall):
    """관 매칭 실패하면 지점 평균 좌석."""
    halls = seat_map.get(branch) or {}
    if not halls:
        return DEFAULT_HALL_SEATS
    if hall and hall in halls and halls[hall]:
        return halls[hall]
    if hall:
        for hno, seats in halls.items():
            if hno and (hall in hno or hno in hall):
                return seats
    vals = [s for s in halls.values() if s]
    return round(sum(vals) / len(vals)) if vals else DEFAULT_HALL_SEATS


_GUID_PAT = re.compile(r'guid=([a-f0-9]{32})')


def fetch_detail_image_guids(event_id):
    """상세 페이지 HTML에서 file.cineq.co.kr guid 추출 (순서 보존)."""
    try:
        html = urlopen(Request(DETAIL_URL + str(event_id),
                               headers={"User-Agent": UA}),
                       timeout=15).read().decode("utf-8", "replace")
    except Exception:
        return []
    return list(dict.fromkeys(_GUID_PAT.findall(html)))


def download_image(url, target):
    if target.exists():
        return False
    try:
        blob = urlopen(Request(url, headers={"User-Agent": UA}),
                       timeout=20).read()
        target.write_bytes(blob)
        return True
    except Exception:
        return False


def fetch_all_events():
    """씨네큐 MoreList 를 끝까지 페이징하며 EventId 기준 중복 제거 수집.

    MoreList 는 eventId 에 '마지막으로 본 이벤트 ID' 를 넘기면 그 다음 묶음을
    돌려준다. 0 으로 시작해 더 이상 새 항목이 없을 때까지 반복한다.
    (eventId=0 한 번만 호출하면 최신 ~12건만 받고 끝나므로 페이징 필수)
    """
    collected = {}
    event_id = 0
    for _ in range(50):          # 안전 상한 (페이지당 ~12건)
        payload = urlencode({'eventId': event_id, 'eventSort': -1}).encode()
        req = Request(API_URL, data=payload, headers={
            "User-Agent": UA,
            "X-Requested-With": "XMLHttpRequest",
        })
        try:
            with urlopen(req, timeout=15) as resp:
                batch = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            if collected:        # 일부라도 모았으면 그걸로 진행
                break
            sys.exit(f"씨네큐 API 호출 실패: {exc}")
        if not batch:
            break
        new = 0
        for item in batch:
            eid = item.get("EventId")
            if eid is not None and eid not in collected:
                collected[eid] = item
                new += 1
        last_id = batch[-1].get("EventId")
        if new == 0 or last_id is None:   # 더 이상 새 항목 없음 → 종료
            break
        event_id = last_id
    return list(collected.values())


def main():
    print("[*] 씨네큐 프로모션 데이터 수집 중...")

    events_json = fetch_all_events()
    if not events_json:
        sys.exit("씨네큐 이벤트를 수집하지 못했습니다.")

    title_map = build_title_map()
    seat_map = build_seat_map()
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    images_downloaded = 0
    movies = {}
    unmatched = []
    type_counter = {"coupon": 0, "stage": 0, "goods": 0, "etc": 0}

    # 종료 1개월 이상 지난 이벤트 제외 (Duration='YYYY.MM.DD~YYYY.MM.DD' 끝값 비교)
    cutoff = (datetime.now(KST) - timedelta(days=30)).strftime("%Y.%m.%d")

    for item in events_json:
        title = item.get("Title", "").strip()
        if not title: continue
        eid = str(item.get("EventId") or "")

        if eid in SALE_EVENTS:        # 판매 단품 — 대시보드·집계 제외
            continue

        # 기간 끝 추출 후 cutoff 비교
        dur = item.get("Duration") or ""
        end = dur.partition("~")[2].strip()
        if end and end < cutoff:
            continue

        ptype = classify(title)
        type_counter[ptype] += 1

        event_rec = {
            "eventId": eid,
            "name": title,
            "type": ptype,
            "duration": dur,
            "fetchedAt": datetime.now(KST).strftime("%Y-%m-%d"),
        }
        if ptype == "goods" and eid in GOODS_THEATERS:
            event_rec["theaters"] = GOODS_THEATERS[eid]
        if ptype == "coupon" and eid in COUPON_COUNTS:
            event_rec["issued"] = COUPON_COUNTS[eid]

        # stage·coupon: 상세 이미지 다운로드 (stage=좌석 판독용, coupon=발행수 판독용).
        # 씨네큐는 발행수가 이미지 안 텍스트라 LLM 이 이 이미지를 읽어 COUPON_COUNTS 등록.
        if ptype in ("stage", "coupon") and eid:
            guids = fetch_detail_image_guids(eid)
            saved = []
            for idx, g in enumerate(guids, 1):
                target = IMG_DIR / f"{eid}_{idx}.jpg"
                if download_image(FILE_URL + g, target):
                    images_downloaded += 1
                if target.exists():
                    saved.append(f"assets/data/cineq_images/{target.name}")
            if guids:
                event_rec["posterUrls"] = [FILE_URL + g for g in guids]
                event_rec["imagePaths"] = saved
            if ptype == "stage" and eid in SCREENINGS:
                screenings = []
                total = 0
                for s in SCREENINGS[eid]:
                    seats_per = lookup_seats(seat_map, s["branch"], s.get("hall"))
                    seats = seats_per * s["sessions"]
                    total += seats
                    screenings.append({**s, "seats": seats})
                event_rec["screenings"] = screenings
                event_rec["seats"] = total
                event_rec["branches"] = sorted({s["branch"] for s in screenings})

        # 1. 괄호 내용 추출 매칭
        brackets = re.findall(r"[<\[\((]([^<>\\[\]\(\)]+)[>\]\)]", title)
        hit = None
        for cand in brackets:
            nc = norm_title(cand)
            if not nc or nc in ("이벤트", "안내", "공지", "단독"): continue
            if nc in title_map:
                hit = title_map[nc]
                break
            for k, v in title_map.items():
                if nc in k or k in nc:
                    hit = v
                    break
            if hit: break
        
        # 2. 전체 제목 매칭
        if not hit:
            norm_t = norm_title(title)
            for k, v in title_map.items():
                if k and k in norm_t:
                    hit = v
                    break

        if hit:
            movie_cd, mv_title = hit
            rec = movies.setdefault(movie_cd, {
                "movieCd": movie_cd, "title": mv_title,
                "counts": {"coupon": 0, "stage": 0, "goods": 0, "etc": 0},
                "promoSeats": 0,
                "events": [],
            })
            rec["counts"][ptype] += 1
            rec["promoSeats"] += event_rec.get("seats", 0)
            rec["events"].append(event_rec)
        else:
            unmatched.append(event_rec)

    out = {
        "chain": "CINEQ",
        "source": "씨네큐 공식 이벤트 API",
        "fetchedAt": datetime.now(KST).isoformat(timespec="seconds"),
        "movies": sorted(movies.values(), key=lambda m: sum(m["counts"].values()), reverse=True),
        "unmatched": unmatched,
    }
    
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"✓ 씨네큐 프로모션 저장 완료: {len(movies)}편 매칭 "
          f"(전체 이벤트 {len(events_json)}건 · 미매칭 {len(unmatched)}건 · "
          f"포스터 이미지 {images_downloaded}건 신규 저장)")
    print(f"  타입 분포: 쿠폰 {type_counter['coupon']} · 무대인사 {type_counter['stage']} · 굿즈 {type_counter['goods']} · 기타 {type_counter['etc']}")
    print("  영화별 promoSeats:")
    for m in out["movies"]:
        if m.get("promoSeats", 0) > 0:
            print(f"    {m['title'][:30]:<30s}  {m['promoSeats']:>6,} 석  "
                  f"(stage={m['counts']['stage']})")


if __name__ == "__main__":
    main()
