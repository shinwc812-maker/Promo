#!/usr/bin/env python3
"""
build_promotions_cgv.py
--------------------------------------------------
fetch_cgv_images.py 가 만든 `_pending.json` (수집된 이벤트 메타) 을
`booking.json` (실시간 예매율 TOP 10) 과 조인해 `promotions_cgv.json` 을 만든다.

이미지에서 직접 판독한 무대인사 일정(지점/관/회차)은 이 파일 상단의
`SCREENINGS` dict 에 evntNo → screenings[] 로 하드코딩한다. 좌석 합산은
`theater_seats_cgv.json` 의 지점·관 좌석수를 조회해 자동 계산.

(이미지 판독 자체는 사람·LLM 이 별도로 수행. 이 스크립트는 단순 조립.)
"""
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

KST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "assets" / "data"
PENDING_FILE = DATA_DIR / "cgv_images" / "_pending.json"
SEATS_FILE = DATA_DIR / "theater_seats_cgv.json"
BOOKING_FILE = DATA_DIR / "booking.json"
AUTO_SCREENINGS_FILE = DATA_DIR / "cgv_auto_screenings.json"
OUT_FILE = DATA_DIR / "promotions_cgv.json"

# 관명은 있으나 좌석 데이터에서 못 찾을 때의 폴백 좌석수 (CGV 일반관 평균).
# 관 자체가 미명시(hall=None)인 경우는 추정하지 않고 좌석 미공개로 둔다.
DEFAULT_HALL_SEATS = 200

# 판매 단품(키링·쿠지 등 유료) — 증정이 아니므로 대시보드·집계에서 완전 제외
SALE_EVENTS = {
    "202604237123",   # 악마는 프라다2 키링 출시 (단품 8,500원)
}

# 쿠폰 발행수 수동 오버라이드. 평소엔 크롤러가 상세 '쿠폰 사용수량' 위젯에서
# 자동 추출(_pending.json 의 couponIssued)하므로 비워둔다. 자동 추출이 틀린
# 경우에만 evntNo → 발행수(매)로 강제 지정. (오버라이드가 자동값보다 우선)
COUPON_COUNTS = {}

# 굿즈·특전 진행관수 (이미지 '대상 극장' 목록 판독). 미등록은 '미공개'.
GOODS_THEATERS = {
    "202605117932": 9,    # 너바나 굿즈패키지
    "202605087835": 27,   # 마이클 IMAX 포스터
    "202605077630": 48,   # 마이클 TTT
    "202605087929": 23,   # 마이클 SCREENX 포스터
    "202605087732": 37,   # 마이클 4DX 포스터
    "202605187853": 1,    # 마이클 팝콘 증정 상영회 (동대문)
    "202605187848": 37,   # 군체 4DX 포스터
    "202605187847": 27,   # 군체 IMAX 포스터
    "202605187647": 24,   # 군체 SCREENX 포스터
    "202604247431": 24,   # 악마 SCREENX 리미티드 포스터
    "202604297337": 48,   # 악마 TTT
    "202605187657": 32,   # 호빵맨 1주차 현장 증정
    "202605147843": 45,   # 신극장판 은혼 TTT
}

# 이미지 판독으로 추출한 무대인사·시사회 일정.
# screenings: {branch, hall, sessions} — hall=None 이면 관 미명시(좌석 미공개)
SCREENINGS = {
    # 군체 개봉일 무대인사 (5/21 용산아이파크몰)
    "202604307547": [
        {"branch": "용산아이파크몰", "hall": "20관", "sessions": 2},   # IMAX LASER 624
        {"branch": "용산아이파크몰", "hall": "16관", "sessions": 1},   # SCREENX 142
        {"branch": "용산아이파크몰", "hall": "6관", "sessions": 2},    # 200
        {"branch": "용산아이파크몰", "hall": "5관", "sessions": 1},    # 186
        {"branch": "용산아이파크몰", "hall": "4관", "sessions": 1},    # SKYBOX 414
        {"branch": "용산아이파크몰", "hall": "7관", "sessions": 1},    # 204
        {"branch": "용산아이파크몰", "hall": "11관", "sessions": 2},   # 194
        {"branch": "용산아이파크몰", "hall": "12관", "sessions": 2},   # 214
        {"branch": "용산아이파크몰", "hall": "13관", "sessions": 1},   # 211
        {"branch": "용산아이파크몰", "hall": "15관", "sessions": 1},   # 247
        {"branch": "용산아이파크몰", "hall": "17관", "sessions": 2},   # PREMIUM 154
    ],
    # 군체 개봉 2주차 무대인사 (5/30 영등포·용산)
    "202605117840": [
        {"branch": "영등포", "hall": "12관", "sessions": 2},    # IMAX LASER 387
        {"branch": "영등포", "hall": "1관", "sessions": 2},     # 358
        {"branch": "용산아이파크몰", "hall": "20관", "sessions": 2},  # IMAX LASER 624
        {"branch": "용산아이파크몰", "hall": "15관", "sessions": 2},  # 247
        {"branch": "용산아이파크몰", "hall": "13관", "sessions": 1},  # 211
    ],
    # 군체설명회 GV (5/22 영등포 5관)
    "202605147943": [
        {"branch": "영등포", "hall": "5관", "sessions": 1},     # 320
    ],
    # 호빵맨 개봉 주 무대인사
    "202605137940": [
        {"branch": "용산아이파크몰", "hall": "16관", "sessions": 2},
        {"branch": "영등포", "hall": "7관", "sessions": 2},
        {"branch": "구로", "hall": "9관", "sessions": 2},
        {"branch": "파주운정", "hall": "5관", "sessions": 2},
        {"branch": "의정부", "hall": "4관", "sessions": 2},
        {"branch": "상봉", "hall": "7관", "sessions": 2},
    ],
    # 와일드 씽 개봉주 무대인사 (6/6~7)
    "202605127938": [
        {"branch": "용산아이파크몰", "hall": "15관", "sessions": 4},
        {"branch": "용산아이파크몰", "hall": "13관", "sessions": 4},
        {"branch": "용산아이파크몰", "hall": "12관", "sessions": 2},
        {"branch": "왕십리", "hall": "7관", "sessions": 2},
        {"branch": "왕십리", "hall": "5관", "sessions": 2},
        {"branch": "영등포", "hall": "5관", "sessions": 2},
        {"branch": "영등포", "hall": "6관", "sessions": 1},
    ],
    # 와일드 씽 CGV회원시사 (5/28 10지점) — 관 미명시 → 좌석 미공개
    "202605117839": [
        {"branch": "광주상무", "hall": None, "sessions": 1},
        {"branch": "대전터미널", "hall": None, "sessions": 1},
        {"branch": "센텀시티", "hall": None, "sessions": 1},
        {"branch": "영등포", "hall": None, "sessions": 1},
        {"branch": "왕십리", "hall": None, "sessions": 1},
        {"branch": "용산아이파크몰", "hall": None, "sessions": 1},
        {"branch": "울산삼산", "hall": None, "sessions": 1},
        {"branch": "의정부", "hall": None, "sessions": 1},
        {"branch": "인천", "hall": None, "sessions": 1},
        {"branch": "천안터미널", "hall": None, "sessions": 1},
    ],
    # 너바나 빠더너스 크루 개봉일 GV (5/20 용산, 관 미명시)
    "202605127937": [
        {"branch": "용산아이파크몰", "hall": None, "sessions": 1},
    ],
    # 너바나 개봉일 무대인사 (5/20 용산 2회, 관 미명시)
    "202605147644": [
        {"branch": "용산아이파크몰", "hall": None, "sessions": 2},
    ],
    # 너바나 한로로 GV (5/26 용산, 관 미명시)
    "202605147645": [
        {"branch": "용산아이파크몰", "hall": None, "sessions": 1},
    ],
    # ── TOP10 stage 보강 (2026-05-26 LLM 포스터 판독) ──
    # 너바나 박정민 GV (6/2 왕십리, 관 미명시)
    "202605208155": [
        {"branch": "왕십리", "hall": None, "sessions": 1},
    ],
    # 너바나 빠더너스 문상훈 무대인사 (5/24 18:40 용산 + 5/26 20:55 중랑 11관)
    "202605187949": [
        {"branch": "용산아이파크몰", "hall": None, "sessions": 1},
        {"branch": "중랑", "hall": "11관", "sessions": 1},
    ],
    # 너바나 빠더너스 문상훈 추가 무대인사 (6/2 청량리, 관 미명시)
    "202605218057": [
        {"branch": "청량리", "hall": None, "sessions": 1},
    ],
    # 뒷자리에 태워줘 천 개의 뒷자리 GV (5/28 용산, 천선란 작가·이학정 GV)
    "202605218157": [
        {"branch": "용산아이파크몰", "hall": None, "sessions": 1},
    ],
    # 와일드 씽 프리미어 시사회 (5/30~31, 전국 ~15개 극장, 관 미명시)
    # 포스터 '진행 극장' 목록 기준 — 일부 지점명은 약어/오기 가능, 좌석DB 매칭 안되면 placeholder
    "202605227960": [
        {"branch": "계양", "hall": None, "sessions": 1},
        {"branch": "광주금남로", "hall": None, "sessions": 1},
        {"branch": "대구수성", "hall": None, "sessions": 1},
        {"branch": "대전", "hall": None, "sessions": 1},
        {"branch": "동수원", "hall": None, "sessions": 1},
        {"branch": "동탄", "hall": None, "sessions": 1},
        {"branch": "상봉", "hall": None, "sessions": 1},
        {"branch": "송파", "hall": None, "sessions": 1},
        {"branch": "영등포", "hall": None, "sessions": 1},
        {"branch": "용인", "hall": None, "sessions": 1},
        {"branch": "일산", "hall": None, "sessions": 1},
        {"branch": "인천", "hall": None, "sessions": 1},
        {"branch": "천안", "hall": None, "sessions": 1},
        {"branch": "청주서문", "hall": None, "sessions": 1},
        {"branch": "홍대", "hall": None, "sessions": 1},
    ],
    # 뒷자리 월간 레이 상영회 (5/29~31, 종로·인천·용산·서면·강남)
    # ※ 분류는 etc 였지만 명백한 상영행사라 SCREENINGS 등록 = stage 강제 승격
    "202605208156": [
        {"branch": "종로", "hall": None, "sessions": 1},
        {"branch": "인천", "hall": None, "sessions": 1},
        {"branch": "용산아이파크몰", "hall": None, "sessions": 1},
        {"branch": "서면", "hall": None, "sessions": 1},
        {"branch": "강남", "hall": None, "sessions": 1},
    ],
    # 뒷자리 레이 브로마이드 상영회 (5/27~ 왕십리·용산, 관람 후 증정형)
    # ※ 분류는 etc 였지만 상영회라 SCREENINGS 등록 = stage 강제 승격
    "202605198151": [
        {"branch": "왕십리", "hall": None, "sessions": 1},
        {"branch": "용산아이파크몰", "hall": None, "sessions": 1},
    ],
}

# 타입 분류 키워드
STAGE_KW = ("무대인사", "GV", "시사회", "관객과의 대화", "관객과의대화",
            "팬미팅", "내한")
COUPON_KW = ("쿠폰", "관람권", "할인", "1+1", "무비싸다구")
GOODS_KW = ("포스터", "특전", "굿즈", "증정", "키링", "TTT", "아트카드",
            "필름마크", "패키지", "콜라보", "오브제", "스티커")


def classify(name):
    """이벤트명 키워드로 프로모션 타입 결정."""
    text = name.replace("CGV", "")
    if any(k in text for k in STAGE_KW):
        return "stage"
    if any(k in text for k in COUPON_KW):
        return "coupon"
    if any(k in text for k in GOODS_KW):
        return "goods"
    # '상영회'는 '프리미어'와 함께 있을 때만 시사회(stage). 그 외 응원·리액션·특별 상영회는 기타.
    # (굿즈·쿠폰성 상영회는 위에서 이미 분기됨)
    if "프리미어" in text and "상영회" in text:
        return "stage"
    return "etc"


def cap_goods_end(start, end, weeks=2):
    """CGV 굿즈 종료일 캡 — '소진 시 종료'라 CGV 명시 종료일이 길게(≈한 달) 잡힌다.
    실제론 그 전에 소진되므로 '시작일+N주'로 넉넉히 캡(원래 종료일이 더 짧으면 그대로 둠)."""
    if not start:
        return end
    try:
        cap = (datetime.strptime(start, "%Y-%m-%d") + timedelta(weeks=weeks)).strftime("%Y-%m-%d")
    except ValueError:
        return end
    return cap if not end else min(end, cap)


def norm_title(text):
    return re.sub(r"[\s\W_]+", "", text or "").lower()


def build_title_map():
    title_map = {}
    if not BOOKING_FILE.exists():
        return title_map
    doc = json.loads(BOOKING_FILE.read_text(encoding="utf-8"))
    for row in doc.get("bookingRate") or []:
        if row.get("movieCd") and row.get("title"):
            title_map[norm_title(row["title"])] = (row["movieCd"], row["title"])
    return title_map


def build_seat_map():
    """지점·관 → 좌석수 (placeholder 도 포함, 'placeholder' 플래그 보존)."""
    if not SEATS_FILE.exists():
        return {}
    doc = json.loads(SEATS_FILE.read_text(encoding="utf-8"))
    theaters = doc.get("theaters") if isinstance(doc, dict) else doc
    out = {}
    for t in theaters or []:
        name = t.get("name", "")
        is_placeholder = bool(t.get("placeholder"))
        halls = {}
        for h in t.get("halls") or []:
            halls[h.get("no", "")] = (h.get("seats", 0), is_placeholder)
        out[name] = halls
    return out


def find_branch_halls(seat_map, branch_query):
    """지점명 부분일치로 halls 딕셔너리 반환."""
    for name, halls in seat_map.items():
        # 'CGV용산아이파크몰' 같이 'CGV' 접두 있을 수도, 'CGV' 제거 후 비교
        clean = name.replace("CGV", "").strip()
        if branch_query == clean or branch_query in name or branch_query in clean:
            return name, halls
    return None, {}


def _hall_num(name):
    """'12관'·'12관 IMAX' → '12'(관 번호). 숫자관이 아니면 None."""
    m = re.match(r"\s*(\d+)\s*관", name or "")
    return m.group(1) if m else None


def lookup_seats(seat_map, branch, hall):
    """branch·hall → (seats, placeholder_flag, matched_branch_name)."""
    bname, halls = find_branch_halls(seat_map, branch)
    if not halls:
        return DEFAULT_HALL_SEATS, True, branch
    if hall is None:
        # 일반관 평균: GOLD/Chef/PrivateBox/BEREX 같은 특수관 제외
        special = ("GOLD", "Chef", "Private", "BEREX", "ArtHouse")
        normal = [s for (s, _) in halls.values()
                  if s > 0]  # 평균은 일단 전체로 (특수관 영향 작음)
        avg = round(sum(normal) / len(normal)) if normal else DEFAULT_HALL_SEATS
        return avg, halls.get(next(iter(halls)), (0, True))[1], bname
    # 관 매칭 (부분 문자열 오매칭 방지: '5관'이 '15관'에, '6관'이 '16관'에 잡히던 버그)
    # 1) 정확 일치
    if hall in halls:
        seats, ph = halls[hall]
        return seats, ph, bname
    # 2) 'N관' 번호가 같은 관 (숫자관은 번호 일치로만 매칭 — 부분 문자열 금지)
    qn = _hall_num(hall)
    if qn is not None:
        for hno, (seats, ph) in halls.items():
            if _hall_num(hno) == qn:
                return seats, ph, bname
    else:
        # 3) 숫자관이 아닌 표기차(IMAX/SCREENX/GOLD 등)만 부분 일치 허용
        for hno, (seats, ph) in halls.items():
            if _hall_num(hno) is None and (hall in hno or hno in hall):
                return seats, ph, bname
    # 못 찾으면 평균
    normal = [s for (s, _) in halls.values() if s > 0]
    avg = round(sum(normal) / len(normal)) if normal else DEFAULT_HALL_SEATS
    return avg, True, bname


def compute_seats(screenings, seat_map):
    """관 명시된 회차만 좌석 합산. 관 미명시(hall=None)는 추정 안 함 → 미공개.

    명시된 관이 하나도 없으면 (전부 hall=None) 좌석수는 None(미공개)을 반환한다.
    """
    total = 0
    any_placeholder = False
    known = 0
    for s in screenings:
        if not s.get("hall"):
            continue                      # 관 미명시 → 좌석 미공개(평균 추정 금지)
        seats_per, ph, _ = lookup_seats(seat_map, s["branch"], s["hall"])
        total += seats_per * s["sessions"]
        any_placeholder = any_placeholder or ph
        known += 1
    return (total if known else None), any_placeholder


def main():
    if not PENDING_FILE.exists():
        sys.exit(f"_pending.json 없음 — fetch_cgv_images.py 먼저 실행: {PENDING_FILE}")
    pending = json.loads(PENDING_FILE.read_text(encoding="utf-8"))
    events_raw = pending.get("events", [])
    if not events_raw:
        sys.exit("_pending.json 에 events 가 없습니다.")

    title_map = build_title_map()
    seat_map = build_seat_map()
    # 자동검출 SCREENINGS (fetch_cgv_booking.py 결과). 수동 SCREENINGS 가 있으면
    # 수동 우선 — auto 는 부킹 API 가 못 잡는 케이스(특수관·미공개 시사회 등)에서
    # 수동 보강 필요해서.
    auto_screenings = {}
    if AUTO_SCREENINGS_FILE.exists():
        try:
            auto_screenings = json.loads(
                AUTO_SCREENINGS_FILE.read_text(encoding="utf-8")
            ).get("events") or {}
        except (json.JSONDecodeError, OSError):
            auto_screenings = {}

    def match_movie(name):
        norm = norm_title(name)
        if not norm:
            return None
        for key, val in title_map.items():
            if norm == key or norm in key or key in norm:
                return val
        return None

    movies = {}
    unmatched = []
    type_counter = {"coupon": 0, "stage": 0, "goods": 0, "etc": 0}
    today = datetime.now(KST).strftime("%Y-%m-%d")

    for ev in events_raw:
        name = (ev.get("title") or "").strip()
        eid = str(ev.get("evntNo") or "")
        if not name:
            continue
        if eid in SALE_EVENTS:        # 판매 단품 — 대시보드·집계 제외
            continue
        ptype = classify(name)
        # SCREENINGS 에 있거나 auto 자동검출 결과가 있으면 무조건 stage 로 강제
        if eid in SCREENINGS or auto_screenings.get(eid):
            ptype = "stage"
        start = ev.get("start", "")
        end = ev.get("end") or ""
        # CGV 굿즈는 '소진 시 종료'라 명시 종료일이 길게 잡힘 → 시작일+2주로 캡.
        if ptype == "goods":
            end = cap_goods_end(start, end)
        # 종료일(end) 지난 이벤트는 타입 무관 모두 제외 (진행중·예정만 집계)
        if end and end < today:
            continue
        type_counter[ptype] += 1

        event_rec = {
            "eventId": eid,
            "name": name,
            "type": ptype,
            "start": start,
            "end": end,
        }
        # auto 가 좌석 매칭(sum>0) 했으면 auto 우선 — 부킹 API 가 hall·좌석을 직접
        # 알려주므로 manual hall=None(미공개) 보다 정확. auto 가 0좌석이거나 없으면
        # manual 사용.
        manual_scr = SCREENINGS.get(eid)
        auto_scr = auto_screenings.get(eid)
        auto_seat_sum = sum((s.get("seats") or 0) for s in (auto_scr or []))
        if auto_scr and auto_seat_sum > 0:
            screenings = auto_scr
            event_rec["autoDetected"] = True
        else:
            screenings = manual_scr or auto_scr
        if screenings:
            seats, has_ph = compute_seats(screenings, seat_map)
            event_rec["screenings"] = screenings
            event_rec["seats"] = seats
            if has_ph:
                event_rec["seatsEstimated"] = True
            event_rec["branches"] = sorted({s["branch"] for s in screenings})
        if ptype == "goods" and eid in GOODS_THEATERS:
            event_rec["theaters"] = GOODS_THEATERS[eid]
        if ptype == "coupon":
            # 수동 오버라이드(COUPON_COUNTS) 우선, 없으면 크롤러 자동 추출값
            issued = COUPON_COUNTS.get(eid) or ev.get("couponIssued")
            if issued:
                event_rec["issued"] = issued

        # 매칭: [영화명]·<영화명> 파싱
        brackets = re.findall(r"[\[<]([^\[\]<>]+)[\]>]", name)
        hit = None
        for cand in brackets:
            cand = cand.strip()
            if not cand:
                continue
            hit = match_movie(cand)
            if hit:
                break
        if not hit:
            hit = match_movie(name)

        if hit:
            movie_cd, mv_title = hit
            rec = movies.setdefault(movie_cd, {
                "movieCd": movie_cd, "title": mv_title, "matched": True,
                "counts": {"coupon": 0, "stage": 0, "goods": 0, "etc": 0},
                "promoSeats": 0,
                "events": [],
            })
            rec["counts"][ptype] += 1
            rec["promoSeats"] += event_rec.get("seats") or 0
            rec["events"].append(event_rec)
        else:
            event_rec["movieName"] = brackets[0].strip() if brackets else None
            unmatched.append(event_rec)

    # --- 종료 이벤트 누적(carry-forward) — 전체 보관 ---
    # 직전 출력에서 종료분을 이월하고, 어제 진행중이었으나 종료일이 지난 이벤트를 승격.
    # (CGV 날짜 포맷은 %Y-%m-%d — 자기 파일 안에서만 비교하므로 일관)
    # movies[](진행중)는 그대로 두므로 counts/promoSeats/실예매 집계엔 영향 없음.
    prev = {}
    if OUT_FILE.exists():
        try:
            prev = json.loads(OUT_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            prev = {}
    ended_by_id = {e["eventId"]: e for e in prev.get("endedEvents", [])}
    _KEEP = ("eventId", "name", "type", "start", "end", "seats", "issued", "theaters")
    for mv in prev.get("movies", []):
        for e in mv.get("events", []):
            ee = e.get("end", "")
            if ee and ee < today and e["eventId"] not in ended_by_id:
                rec = {k: e[k] for k in _KEEP if k in e}
                rec.update(ended=True, end=ee,
                           movieCd=mv["movieCd"], movieTitle=mv["title"])
                ended_by_id[e["eventId"]] = rec

    out = {
        "chain": "CGV",
        "source": "CGV 이벤트 상세 포스터 이미지 분석 + 좌석 합산",
        "fetchedAt": datetime.now(KST).isoformat(timespec="seconds"),
        "movies": sorted(movies.values(),
                         key=lambda m: sum(m["counts"].values()),
                         reverse=True),
        "unmatched": unmatched,
        "endedEvents": sorted(ended_by_id.values(),
                              key=lambda e: e.get("end", ""), reverse=True),
    }
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(out, ensure_ascii=False, indent=2),
                        encoding="utf-8")

    matched_events = sum(len(m["events"]) for m in out["movies"])
    print(f"✓ CGV 프로모션 저장 → {OUT_FILE.relative_to(ROOT)}")
    print(f"  진행 이벤트 {matched_events + len(unmatched)}건 · "
          f"영화 매칭 {len(out['movies'])}편 · 미매칭 {len(unmatched)}건")
    print(f"  타입 분포: 쿠폰 {type_counter['coupon']} · "
          f"무대인사 {type_counter['stage']} · 굿즈 {type_counter['goods']} · "
          f"기타 {type_counter['etc']}")
    print("  영화별 promoSeats:")
    for m in out["movies"]:
        print(f"    {m['title'][:30]:<30s}  {m['promoSeats']:>6,} 석  "
              f"(stage={m['counts']['stage']}·goods={m['counts']['goods']}"
              f"·coupon={m['counts']['coupon']}·etc={m['counts']['etc']})")


if __name__ == "__main__":
    main()
