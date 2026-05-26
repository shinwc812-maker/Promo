#!/usr/bin/env python3
"""
fetch_cgv_booking.py
--------------------------------------------------
CGV 부킹 시스템(api.cgv.co.kr) 에서 TOP10 영화의 프리미어/GV/무대인사/시사회
회차를 자동 추출해 `assets/data/cgv_auto_screenings.json` 으로 저장한다.

CGV API 는 x-signature 헤더로 동적 서명돼 직접 호출 불가([[cgv-booking-api]]).
Selenium 헤드리스 Chrome 으로 부킹 페이지를 띄우고, 페이지 axios 가 서명한
응답을 fetch 후킹 JS 로 캡처하는 방식.

흐름:
  1. _pending.json(이벤트) + booking.json(TOP10) 읽기
  2. stage 키워드(프리미어/GV/무대인사/시사회) 가진 _pending 이벤트 중 TOP10
     영화에 매칭되는 것만 자동검출 대상
  3. Chrome 띄움 + fetch 후킹 주입 + CGV 부킹 페이지 진입
  4. searchAtktTopPostrList 응답 캡처 → 영화명→movNo 매핑
  5. 각 대상 이벤트:
     - movNo + 이벤트 기간(start..end) 식별
     - 후보 사이트 × 날짜 별 URL navigation → searchSchByMov 응답 캡처
     - prodNm/expoProdNm 에 stage 태그 ('프리미어'/'GV'/'무대인사'/'시사') 포함
       회차만 추리고 (branch,hall) 별로 sessions/seats 집계
  6. {evntNo: [{branch,hall,sessions,seats}]} 로 저장

`build_promotions_cgv.py` 가 이 파일을 수동 SCREENINGS dict 와 머지(수동 우선).

의존성: selenium, webdriver-manager (이미 fetch_cgv_images.py 와 공유).
"""
import json
import re
import sys
import time
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
BOOKING_FILE = DATA_DIR / "booking.json"
OUT_FILE = DATA_DIR / "cgv_auto_screenings.json"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
BOOK_PAGE = "https://cgv.co.kr/cnm/movieBook/movie"

# 시사회/GV/무대인사 식별 키워드. CGV 부킹 응답의 prodNm/expoProdNm/
# videoAddexpCont 에 "(프리미어 상영)", "(GV)", "(무대인사)" 형태로 박혀있음.
STAGE_TAGS = ("프리미어", "GV", "무대인사", "시사회", "관객과의대화")

# 자동검출 대상 region 코드 — searchAllRegionAndSite 응답 regionInfo 에서
# 01=서울 02=경기 03=인천 04=강원 05=대전/충청 06=대구 07=부산/울산
# 08=경상 09=광주/전라/제주. 시사회·GV·무대인사가 거의 수도권 메이저관에서
# 열려 일일 배치 시간 절약 위해 01·02·03 만. 누락 사이트가 의심되면 region
# 추가(전국 = ~130곳, 수도권만 = ~80곳, 사이트당 nav 약 2.5초).
TARGET_REGIONS = {"01", "02", "03"}

# 페이지 로드 후 schByMov 호출까지 대기 시간(초). 너무 짧으면 응답 누락,
# 너무 길면 배치 시간 폭증. 헤드리스 Chrome 에서 2.5초가 안정 마지노선.
NAV_SLEEP = 2.5

# 페이지에 주입할 fetch 훅 — 모든 응답을 window.__cap 에 누적
FETCH_HOOK = """
window.__cap = [];
const orig = window.fetch;
window.fetch = function(...args) {
    const url = (typeof args[0] === 'string') ? args[0] : args[0].url;
    return orig.apply(this, args).then(async (r) => {
        try {
            const t = await r.clone().text();
            window.__cap.push({url: url, status: r.status,
                               body: t.slice(0, 120000)});
        } catch (e) {}
        return r;
    });
};
"""


def norm_title(text):
    return re.sub(r"[\s\W_]+", "", text or "").lower()


def make_driver():
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from webdriver_manager.chrome import ChromeDriverManager
    opts = Options()
    for a in ("--headless=new", "--no-sandbox", "--disable-dev-shm-usage",
              "--window-size=1400,3000", "--log-level=3"):
        opts.add_argument(a)
    opts.add_argument(f"user-agent={UA}")
    return webdriver.Chrome(
        service=Service(ChromeDriverManager().install()), options=opts)


def fetch_movie_and_site_lists(driver):
    """부킹 페이지 첫 진입 → 영화 코드 매핑 + region별 사이트 list 추출.

    반환: ({normTitle: (movNo, movNm)}, [(siteNo, siteNm), ...])
    사이트는 TARGET_REGIONS 안 것만 (시사회·GV 진행 가능성 높은 지역).
    """
    driver.execute_script("window.__cap = [];")
    driver.get(BOOK_PAGE)
    time.sleep(6)
    cap = driver.execute_script("return window.__cap;") or []
    movie_map = {}
    sites = []
    seen = set()
    for c in cap:
        u = c.get("url") or ""
        if "searchAtktTopPostrList" in u and not movie_map:
            try:
                doc = json.loads(c["body"])
            except json.JSONDecodeError:
                continue
            for it in doc.get("data") or []:
                nm = it.get("movNm") or ""
                no = it.get("movNo")
                if nm and no:
                    movie_map[norm_title(nm)] = (no, nm)
        elif "searchAllRegionAndSite" in u and not sites:
            try:
                doc = json.loads(c["body"])
            except json.JSONDecodeError:
                continue
            for s in (doc.get("data") or {}).get("siteInfo") or []:
                rg = s.get("regnGrpCd")
                site_no = s.get("siteNo")
                site_nm = s.get("siteNm")
                if rg in TARGET_REGIONS and site_no and site_no not in seen:
                    sites.append((site_no, site_nm))
                    seen.add(site_no)
    return movie_map, sites


def match_movie(title_map, query):
    nq = norm_title(query)
    if not nq:
        return None
    for k, val in title_map.items():
        if nq == k or nq in k or k in nq:
            return val
    return None


def event_date_range(event, today):
    """이벤트 start/end → 오늘 이상 날짜 list. start 없거나 end 과거면 [].

    end 가 비어있으면 start +14일로 캡(과도한 스캔 방지).
    """
    start = event.get("start") or ""
    end = event.get("end") or ""
    try:
        sd = datetime.strptime(start, "%Y-%m-%d").date()
    except ValueError:
        return []
    try:
        ed = datetime.strptime(end, "%Y-%m-%d").date()
    except ValueError:
        ed = sd + timedelta(days=14)
    if ed < today:
        return []
    sd = max(sd, today)
    ed = min(ed, today + timedelta(days=14))   # 14일 캡
    return [sd + timedelta(days=i) for i in range((ed - sd).days + 1)]


def detect_event_subtag(name):
    """이벤트명에서 sub-tag 검출 — booking 응답 필터에 사용."""
    for kw, tag in (("프리미어", "프리미어"), ("무대인사", "무대인사"),
                    ("시사회", "시사"), ("GV", "GV")):
        if kw in name:
            return tag
    return None


def scan_sessions(driver, mov_no, sites, dates, cache):
    """sites × dates 만큼 URL nav → searchSchByMov 응답 행 누적.

    cache: dict((mov_no, site_no, ymd) -> list[row]) — 같은 영화 다른 이벤트가
    겹치는 dates 를 재호출 안 함. 호출 후 결과를 캐시에 저장.
    """
    rows = []
    for site_no, _site_nm in sites:
        for d in dates:
            ymd = d.strftime("%Y%m%d")
            key = (mov_no, site_no, ymd)
            if key in cache:
                rows.extend(cache[key])
                continue
            url = (f"{BOOK_PAGE}?movNo={mov_no}"
                   f"&siteNo={site_no}&scnsYmd={ymd}")
            driver.execute_script("window.__cap = [];")
            try:
                driver.get(url)
            except Exception:
                cache[key] = []
                continue
            time.sleep(NAV_SLEEP)
            cap = driver.execute_script("return window.__cap;") or []
            site_rows = []
            for c in cap:
                u = c.get("url") or ""
                if "searchSchByMov" not in u:
                    continue
                if f"siteNo={site_no}" not in u or f"scnYmd={ymd}" not in u:
                    continue
                try:
                    doc = json.loads(c["body"])
                except (json.JSONDecodeError, KeyError):
                    continue
                for it in doc.get("data") or []:
                    site_rows.append(it)
            cache[key] = site_rows
            rows.extend(site_rows)
    return rows


def is_stage_row(row):
    text = " ".join(s for s in (row.get("prodNm"), row.get("expoProdNm"),
                                row.get("videoAddexpCont")) if s)
    return any(tag in text for tag in STAGE_TAGS)


def normalize_hall(name):
    """'16관 (Laser)' → '16관'. 숫자관이 아닌 표기(IMAX/SCREENX 등)는 그대로."""
    if not name:
        return ""
    m = re.match(r"^\s*(\d+\s*관)", name)
    return m.group(1).replace(" ", "") if m else name.strip()


def aggregate(rows, subtag):
    """프리미어/GV/무대인사 etc 키워드로 필터 후 (branch, hall) 별 집계."""
    bucket = {}
    for r in rows:
        if not is_stage_row(r):
            continue
        if subtag:
            text = " ".join(s for s in (r.get("prodNm"), r.get("expoProdNm"),
                                         r.get("videoAddexpCont")) if s)
            if subtag not in text:
                continue
        branch = (r.get("siteNm") or "").replace("CGV ", "").strip()
        hall = normalize_hall(r.get("scnsNm") or r.get("expoScnsNm") or "")
        if not branch or not hall:
            continue
        seats_per = int(r.get("stcnt") or 0)
        key = (branch, hall)
        bucket.setdefault(key, {"sessions": 0, "seats": 0})
        bucket[key]["sessions"] += 1
        bucket[key]["seats"] += seats_per
    return [
        {"branch": b, "hall": h,
         "sessions": v["sessions"], "seats": v["seats"]}
        for (b, h), v in bucket.items()
    ]


def _load_manual_screening_ids():
    """좌석 매칭된 수동 SCREENINGS eid 만 skip.

    수동 SCREENINGS 인데 모든 회차가 hall=None(좌석 미공개)이면 자동검출 시도해
    좌석을 채울 가치가 있음. 적어도 한 회차라도 hall 명시(좌석 매칭)된 eid 는
    이미 안정된 데이터로 보고 자동검출 스킵(시간 절약).
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        from build_promotions_cgv import SCREENINGS as MAN
    except Exception:
        return set()
    return {eid for eid, scrs in MAN.items()
            if any(s.get("hall") for s in (scrs or []))}


def main():
    if not PENDING_FILE.exists():
        sys.exit(f"_pending.json 없음: {PENDING_FILE}")
    if not BOOKING_FILE.exists():
        sys.exit(f"booking.json 없음: {BOOKING_FILE}")
    pending = json.loads(PENDING_FILE.read_text(encoding="utf-8"))
    booking = json.loads(BOOKING_FILE.read_text(encoding="utf-8"))

    top10 = {norm_title(r["title"]): (r["movieCd"], r["title"])
             for r in booking.get("bookingRate") or []}
    today = datetime.now(KST).date()
    manual_ids = _load_manual_screening_ids()
    print(f"수동 SCREENINGS 등록 이벤트 {len(manual_ids)}건 (자동검출 스킵)")

    # 1) 자동검출 대상 식별
    targets = []
    for ev in pending.get("events", []):
        title = (ev.get("title") or "").strip()
        eid = str(ev.get("evntNo") or "")
        if eid in manual_ids:
            continue
        if not any(t in title for t in STAGE_TAGS):
            continue
        brackets = re.findall(r"[\[<]([^\[\]<>]+)[\]>]", title)
        mv_hit = None
        for b in brackets:
            nb = norm_title(b)
            if not nb:
                continue
            for ntitle, (mvcd, mvtitle) in top10.items():
                if nb == ntitle or nb in ntitle or ntitle in nb:
                    mv_hit = (mvcd, mvtitle)
                    break
            if mv_hit:
                break
        if not mv_hit:
            continue
        dates = event_date_range(ev, today)
        if not dates:
            continue
        targets.append({
            "evntNo": eid,
            "title": title, "movieTitle": mv_hit[1],
            "subtag": detect_event_subtag(title), "dates": dates,
        })

    print(f"자동검출 대상 stage 이벤트: {len(targets)}건")
    for t in targets:
        d0, dN = t["dates"][0], t["dates"][-1]
        print(f"  {t['evntNo']} [{t['movieTitle'][:14]}] {t['title'][:50]} "
              f"({d0}~{dN} {len(t['dates'])}일, sub={t['subtag']})")

    if not targets:
        out = {"fetchedAt": datetime.now(KST).isoformat(timespec="seconds"),
               "source": "CGV booking API auto-scan", "events": {}}
        OUT_FILE.write_text(json.dumps(out, ensure_ascii=False, indent=2),
                            encoding="utf-8")
        print(f"\n자동검출 대상 0건 → 빈 파일 저장: "
              f"{OUT_FILE.relative_to(ROOT)}")
        return

    # 2) Selenium 띄우고 영화 코드 매핑 + 스캔
    driver = make_driver()
    started = time.time()
    try:
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument",
                               {"source": FETCH_HOOK})
        mv_codes, sites = fetch_movie_and_site_lists(driver)
        print(f"\nCGV 영화 코드 {len(mv_codes)}편 · 후보 사이트 {len(sites)}곳 "
              f"(region {sorted(TARGET_REGIONS)})")

        results = {}
        nav_cache = {}      # (mov_no, site_no, ymd) → rows
        for t in targets:
            mvhit = match_movie(mv_codes, t["movieTitle"])
            if not mvhit:
                print(f"\n  ⚠ CGV movNo 매칭 실패: {t['movieTitle']} "
                      f"(부킹에 영화 미노출)")
                continue
            mov_no, mov_nm = mvhit
            print(f"\n  → {t['evntNo']} {t['title'][:40]}")
            print(f"     movNo={mov_no} ({mov_nm}), "
                  f"{len(sites)} 사이트 × {len(t['dates'])}일 "
                  f"(영화별 캐시)")
            t0 = time.time()
            cache_before = len(nav_cache)
            rows = scan_sessions(driver, mov_no, sites,
                                 t["dates"], nav_cache)
            nav_done = len(nav_cache) - cache_before
            screenings = aggregate(rows, t["subtag"])
            results[t["evntNo"]] = screenings
            total_seats = sum(s["seats"] for s in screenings)
            elapsed = time.time() - t0
            print(f"     {elapsed:.0f}초 · nav {nav_done} · 행 {len(rows)} → "
                  f"슬롯 {len(screenings)} · 좌석 {total_seats}")

        out = {
            "fetchedAt": datetime.now(KST).isoformat(timespec="seconds"),
            "source": "CGV booking API auto-scan (searchSchByMov)",
            "events": results,
        }
        OUT_FILE.write_text(json.dumps(out, ensure_ascii=False, indent=2),
                            encoding="utf-8")
        total_elapsed = time.time() - started
        print(f"\n✓ 저장 → {OUT_FILE.relative_to(ROOT)} "
              f"({len(results)} 이벤트, 총 {total_elapsed:.0f}초)")
    finally:
        driver.quit()


if __name__ == "__main__":
    main()
