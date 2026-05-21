#!/usr/bin/env python3
"""
fetch_promotions_megabox.py
--------------------------------------------------
메가박스 이벤트 목록 API(eventMngDiv.do)를 호출해 영화별 프로모션
현황을 assets/data/promotions_megabox.json 으로 생성한다.

Phase 4(4사 프로모션 크롤러)의 두 번째 체인. 출력 JSON 스키마는
롯데(promotions_lotte.json)와 동일한 4사 공통 템플릿이다.

호출:
  POST https://www.megabox.co.kr/on/oh/ohe/Event/eventMngDiv.do
  params: currentPage, eventStatCd=ONG  → 이벤트 카드 HTML 조각 반환
  (전통적 JSP 사이트 · 서버 렌더링 HTML · 브라우저 불필요)

영화 매칭: 이벤트명의 <영화명> 을 boxoffice.json / booking.json 의
movieCd 와 조인한다.

의존성: 파이썬 표준 라이브러리만 사용 (pip install · API 키 불필요)
"""
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

# Windows 콘솔(cp949)에서 한글 메시지가 깨지지 않도록 출력 인코딩 고정
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

KST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "assets" / "data"
OUT_FILE = DATA_DIR / "promotions_megabox.json"
IMG_DIR = DATA_DIR / "megabox_images"
SEATS_FILE = DATA_DIR / "theater_seats_megabox.json"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
EVENT_PAGE = "https://www.megabox.co.kr/event"
DETAIL_URL = "https://www.megabox.co.kr/event/detail?eventNo="
IMG_CDN = "https://img.megabox.co.kr"
API_URL = "https://www.megabox.co.kr/on/oh/ohe/Event/eventMngDiv.do"
MAX_PAGES = 30   # 안전 상한

DEFAULT_HALL_SEATS = 150  # 관 매칭 실패 시 fallback

# 판매 단품(쿠지·드링크 등 유료) — 증정 아니므로 대시보드·집계 제외
SALE_EVENTS = {
    "20619",   # 내 마음의 위험한 녀석 쿠지 단품 11,000원
    "20618",   # 신극장판 은혼 엘리자베스 드링크 25,000원
}

# 쿠폰 발행수 수동 오버라이드. 평소엔 크롤러가 빵원티켓 등 쿠폰 상세 본문의
# '선착순 N명' 에서 자동 추출한다. 자동값이 틀릴 때만 eventNo → 발행수로 지정.
COUPON_COUNTS = {}

# 굿즈·특전 진행관수 (이미지 '진행 극장' 목록 판독). 미등록은 '미공개'.
GOODS_THEATERS = {
    "20629": 52,   # 내 마음의 위험한 녀석 개봉주 현장 증정
}

# 이미지 판독으로 추출한 무대인사 일정 (지점·관·sessions)
# Megabox 본문은 일정표가 이미지에만 있어 사람·LLM 이 판독한 결과를 여기 하드코딩.
# 좌석은 theater_seats_megabox.json 의 지점·관 좌석수로 자동 합산.
SCREENINGS = {
    # 와일드 씽 개봉주 무대인사 (6/6 코엑스, 6/7 상암·목동)
    "20591": [
        # 6/6 코엑스 — Dolby Cinema 2회 + 3관 2회 + 2관 1회
        {"branch": "코엑스", "hall": "Dolby Cinema", "sessions": 2},
        {"branch": "코엑스", "hall": "3관", "sessions": 2},
        {"branch": "코엑스", "hall": "2관", "sessions": 1},
        # 6/7 상암월드컵경기장 — Dolby Vision Atmos 2회 + 1관 1회
        {"branch": "상암월드컵경기장", "hall": "Dolby Vision Atmos", "sessions": 2},
        {"branch": "상암월드컵경기장", "hall": "1관", "sessions": 1},
        # 6/7 목동 — Dolby Vision Atmos 2회 + 2관 1회
        {"branch": "목동", "hall": "Dolby Vision Atmos", "sessions": 2},
        {"branch": "목동", "hall": "2관", "sessions": 1},
    ],
    # 군체 개봉 2주차 무대인사 (5/30 목동 Dolby Vision Atmos 2회 + 2관 2회)
    "20581": [
        {"branch": "목동", "hall": "Dolby Vision Atmos", "sessions": 2},
        {"branch": "목동", "hall": "2관", "sessions": 2},
    ],
}

# 타입 분류 키워드 (우선순위 순) — 롯데 크롤러와 동일 기준 + 메가박스 굿즈명
STAGE_KW = ("무대인사", "GV", "시사회", "관객과의 대화", "관객과의대화")
COUPON_KW = ("무비싸다구", "쿠폰", "관람권", "할인", "빵원티켓", "빵원")
GOODS_KW = ("특전", "굿즈", "오브제", "아트카드", "증정", "포토카드",
            "오리지널 티켓", "오리지널티켓")

# 쿠폰(빵원티켓 등) 상세 본문의 '선착순 N명' 총 발행 수량 패턴
_COUPON_QTY_PAT = re.compile(r"선착순\s*([\d,]+)\s*명")


def classify(name):
    """이벤트명 키워드로 프로모션 타입 결정."""
    if any(k in name for k in STAGE_KW):
        return "stage"
    if any(k in name for k in COUPON_KW):
        return "coupon"
    if any(k in name for k in GOODS_KW):
        return "goods"
    return "etc"


def norm_title(text):
    """매칭용 제목 정규화 — 공백·문장부호 제거 후 소문자화."""
    return re.sub(r"[\s\W_]+", "", text or "").lower()


class EventCardParser(HTMLParser):
    """eventMngDiv.do 응답의 <a class="eventBtn"> 카드를 파싱."""

    def __init__(self):
        super().__init__()
        self.events = []
        self._in_card = False
        self._cur = None
        self._field = None      # 'tit' | 'date' | None
        self._buf = []

    def handle_starttag(self, tag, attrs):
        attr = dict(attrs)
        if tag == "a" and "eventBtn" in (attr.get("class") or ""):
            self._in_card = True
            self._cur = {"no": attr.get("data-no", ""), "title": "", "date": ""}
        elif tag == "p" and self._in_card:
            cls = attr.get("class") or ""
            if "tit" in cls:
                self._field, self._buf = "title", []
            elif "date" in cls:
                self._field, self._buf = "date", []
            else:
                self._field = None

    def handle_data(self, data):
        if self._in_card and self._field:
            self._buf.append(data)

    def handle_endtag(self, tag):
        if tag == "p" and self._field:
            text = re.sub(r"\s+", " ", "".join(self._buf)).strip()
            self._cur[self._field] = text
            self._field = None
        elif tag == "a" and self._in_card:
            self._in_card = False
            if self._cur and self._cur["no"] and self._cur["title"]:
                self.events.append(self._cur)
            self._cur = None


def fetch_events():
    """eventMngDiv.do 를 페이징하며 진행 중 이벤트를 EventID 기준 중복 제거 수집."""
    collected = {}
    for page in range(1, MAX_PAGES + 1):
        body = urlencode({"currentPage": str(page),
                          "eventStatCd": "ONG"}).encode("utf-8")
        request = Request(API_URL, data=body, headers={
            "User-Agent": UA,
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Referer": EVENT_PAGE,
            "X-Requested-With": "XMLHttpRequest",
        })
        try:
            with urlopen(request, timeout=25) as resp:
                html = resp.read().decode("utf-8", errors="replace")
        except (HTTPError, URLError) as exc:
            sys.exit(f"메가박스 이벤트 API 호출 실패 (page={page}): {exc}")

        parser = EventCardParser()
        parser.feed(html)
        if not parser.events:        # 더 이상 이벤트 없음 → 종료
            break
        new = 0
        for ev in parser.events:
            if ev["no"] not in collected:
                collected[ev["no"]] = ev
                new += 1
        if new == 0:                 # 중복만 → 종료
            break
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
    """지점 → halls 리스트({no, seats, type?}) lookup. type 필드까지 보존."""
    if not SEATS_FILE.exists():
        return {}
    doc = json.loads(SEATS_FILE.read_text(encoding="utf-8"))
    theaters = doc.get("theaters") if isinstance(doc, dict) else doc
    out = {}
    for t in theaters or []:
        out[t.get("name", "")] = t.get("halls") or []
    return out


def lookup_seats(seat_map, branch, hall):
    """지점·관 매칭 — 특수관 이름(Dolby Cinema 등)은 type 필드로 매칭."""
    halls = seat_map.get(branch) or []
    if not halls:
        return DEFAULT_HALL_SEATS
    # 1. 정확한 관 번호 매칭 (no 필드)
    for h in halls:
        if h.get("no") == hall and h.get("seats"):
            return h["seats"]
    # 2. type 필드 매칭 — "Dolby Cinema" → type=Dolby Cinema 인 관
    for h in halls:
        if h.get("type") and h.get("seats"):
            if hall in h["type"] or h["type"] in hall:
                return h["seats"]
    # 3. 부분 매칭 — "2관" in "2관"
    for h in halls:
        no = h.get("no", "")
        if no and h.get("seats") and (hall == no or hall in no or no in hall):
            return h["seats"]
    # 4. 못 찾으면 지점 평균
    vals = [h["seats"] for h in halls if h.get("seats")]
    return round(sum(vals) / len(vals)) if vals else DEFAULT_HALL_SEATS


# Megabox 상세 본문 이미지 URL 패턴 — backslash 인코딩 회피 위해 forward-slash 후 매칭
_IMG_PAT = re.compile(r'src="(/?SharedImg/editorImg/[^"]+\.(?:jpg|png|gif))"')


def fetch_detail_images(event_id):
    """이벤트 상세 페이지에서 본문(event-detail) 영역의 editorImg URL 들 반환."""
    try:
        html = urlopen(Request(DETAIL_URL + event_id, headers={"User-Agent": UA}),
                       timeout=20).read().decode("utf-8", "replace")
    except (HTTPError, URLError):
        return []
    pos = html.find('class="event-detail"')
    if pos < 0:
        return []
    section = html[pos:pos + 30000].replace("\\", "/")
    paths = _IMG_PAT.findall(section)
    return [IMG_CDN + (p if p.startswith("/") else "/" + p) for p in paths]


def fetch_coupon_issued(event_id):
    """쿠폰(빵원티켓 등) 상세 본문에서 '선착순 N명' 총 발행 수량 추출. 없으면 None.

    예: '[와일드 씽] 선착순 빵원티켓' 상세 → '선착순 3,000명까지' → 3000.
    멤버십·제휴 할인쿠폰은 수량 문구가 없어 None.
    """
    try:
        html = urlopen(Request(DETAIL_URL + event_id, headers={"User-Agent": UA}),
                       timeout=20).read().decode("utf-8", "replace")
    except (HTTPError, URLError):
        return None
    text = re.sub(r"<[^>]+>", " ", html)
    m = _COUPON_QTY_PAT.search(text)
    return int(m.group(1).replace(",", "")) if m else None


def download_image(url, target):
    if target.exists():
        return False
    try:
        blob = urlopen(Request(url, headers={"User-Agent": UA}),
                       timeout=20).read()
        target.write_bytes(blob)
        return True
    except (HTTPError, URLError):
        return False


def main():
    events = fetch_events()
    if not events:
        sys.exit("수집된 이벤트가 없습니다. (API 구조 변경 가능성)")

    title_map = build_title_map()
    seat_map = build_seat_map()
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    images_downloaded = 0

    def match_movie(movie_name):
        norm = norm_title(movie_name)
        if not norm:
            return None
        for key, val in title_map.items():
            if norm == key or norm in key or key in norm:
                return val
        return None

    movies = {}
    unmatched = []
    type_counter = {"coupon": 0, "stage": 0, "goods": 0, "etc": 0}
    today = datetime.now(KST).strftime("%Y.%m.%d")

    for ev in events:
        title = ev["title"]
        eid = ev["no"]
        if eid in SALE_EVENTS:        # 판매 단품 — 대시보드·집계 제외
            continue
        ptype = classify(title)
        start, _, end = ev["date"].partition("~")
        start, end = start.strip(), end.strip()
        # 무대인사·시사회·GV: 상영일(end) 지나면 즉시 제외 (예매→상영되면 박스오피스로 전환)
        if ptype == "stage" and end and end < today:
            continue
        type_counter[ptype] += 1
        event_rec = {
            "eventId": eid,
            "name": title,
            "type": ptype,
            "start": start,
            "end": end,
        }
        if ptype == "goods" and eid in GOODS_THEATERS:
            event_rec["theaters"] = GOODS_THEATERS[eid]
        if ptype == "coupon":
            # 수동 오버라이드 우선, 없으면 상세 본문 '선착순 N명' 자동 추출
            issued = COUPON_COUNTS.get(eid) or fetch_coupon_issued(eid)
            if issued:
                event_rec["issued"] = issued

        # stage: 본문 이미지 다운로드 + SCREENINGS dict 이 있으면 좌석 합산
        if ptype == "stage":
            img_urls = fetch_detail_images(eid)
            saved_paths = []
            for idx, u in enumerate(img_urls, 1):
                target = IMG_DIR / f"{eid}_{idx}.jpg"
                if download_image(u, target):
                    images_downloaded += 1
                if target.exists():
                    saved_paths.append(f"assets/data/megabox_images/{target.name}")
            if img_urls:
                event_rec["posterUrls"] = img_urls
                event_rec["imagePaths"] = saved_paths
            if eid in SCREENINGS:
                screenings = []
                total = 0
                for s in SCREENINGS[eid]:
                    seats_per = lookup_seats(seat_map, s["branch"], s["hall"])
                    seats = seats_per * s["sessions"]
                    total += seats
                    screenings.append({**s, "seats": seats})
                event_rec["screenings"] = screenings
                event_rec["seats"] = total
                event_rec["branches"] = sorted({s["branch"] for s in screenings})

        # 영화명은 <꺾쇠> 또는 [대괄호] 둘 다 사용됨 (빵원티켓은 [대괄호])
        brackets = [b.strip() for b in re.findall(r"[\[<]([^\[\]<>]+)[\]>]", title)]
        hit = None
        for cand in brackets:
            if cand in ("전체", ""):
                continue
            hit = match_movie(cand)
            if hit:
                break
        if hit:
            movie_cd, mv_title = hit
            rec = movies.setdefault(movie_cd, {
                "movieCd": movie_cd, "title": mv_title, "matched": True,
                "counts": {"coupon": 0, "stage": 0, "goods": 0, "etc": 0},
                "promoSeats": 0,
                "events": [],
            })
            rec["counts"][ptype] += 1
            rec["promoSeats"] += event_rec.get("seats", 0)
            rec["events"].append(event_rec)
        else:
            event_rec["movieName"] = brackets[0] if brackets else None
            unmatched.append(event_rec)

    out = {
        "chain": "MEGABOX",
        "source": "메가박스 이벤트 API · eventMngDiv.do",
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
    print(f"✓ 메가박스 프로모션 저장 → {OUT_FILE.relative_to(ROOT)}")
    print(f"  진행 이벤트 {matched_events + len(unmatched)}건 · "
          f"영화 매칭 {len(out['movies'])}편 · 미매칭 {len(unmatched)}건 · "
          f"포스터 이미지 {images_downloaded}건 신규 저장")
    print(f"  타입 분포: 쿠폰 {type_counter['coupon']} · "
          f"무대인사 {type_counter['stage']} · 굿즈 {type_counter['goods']} · "
          f"기타 {type_counter['etc']}")
    print("  영화별 promoSeats:")
    for m in out["movies"]:
        if m.get("promoSeats", 0) > 0:
            print(f"    {m['title'][:30]:<30s}  {m['promoSeats']:>6,} 석  "
                  f"(stage={m['counts']['stage']})")


if __name__ == "__main__":
    main()
