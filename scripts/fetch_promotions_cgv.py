#!/usr/bin/env python3
"""
fetch_promotions_cgv.py
--------------------------------------------------
CGV 이벤트 크롤러.

CGV 이벤트 API(searchEvtListForPage)는 x-signature 서명을 요구해 외부에서
직접 호출이 불가하다. 그래서 실제 Chrome(Selenium)으로 CGV 이벤트/혜택 탭을
정상적으로 탐색하면, CGV 자기 JS 가 서명해서 목록을 불러온다. 그 응답을
CDP(Chrome DevTools Protocol)로 캡처한다. — 서명 위조가 아니라 정상 브라우저로
접속해 렌더된 결과를 읽는 것.

수집 절차:
  1. cgv.co.kr 접속 → 이벤트/혜택 탭 클릭 → 서브탭 순회 + 스크롤
  2. CGV JS 가 호출한 searchEvtListForPage 응답을 CDP 로 캡처 → 진행중 이벤트 전체
  3. 이벤트명(evntNm)으로 타입 분류 + [영화명] 파싱해 booking.json
     (실시간 예매율 TOP 10) movieCd 와 매칭
  4. assets/data/promotions_cgv.json 생성 (4사 공통 스키마)

* 무대인사 진행 '지점'까지 필요하면 이벤트 상세 포스터 이미지를 별도 분석.
  (목록 API 만으로 영화·타입 분류는 충분)

의존성: selenium, webdriver-manager (+ 로컬 Chrome)
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
OUT_FILE = DATA_DIR / "promotions_cgv.json"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# 타입 분류 키워드 (우선순위 순)
STAGE_KW = ("무대인사", "GV", "시사회", "관객과의 대화", "관객과의대화",
            "팬미팅", "내한")
COUPON_KW = ("쿠폰", "관람권", "할인", "1+1", "무비싸다구")
GOODS_KW = ("포스터", "특전", "굿즈", "증정", "키링", "TTT", "아트카드",
            "필름마크", "패키지", "콜라보", "오브제")


def classify(name):
    """이벤트명 키워드로 프로모션 타입 결정."""
    # 'CGV' 브랜드명의 'GV' 가 무대인사 키워드 'GV' 로 오인되지 않게 제거
    text = name.replace("CGV", "")
    if any(k in text for k in STAGE_KW):
        return "stage"
    if any(k in text for k in COUPON_KW):
        return "coupon"
    if any(k in text for k in GOODS_KW):
        return "goods"
    return "etc"


def norm_title(text):
    """매칭용 제목 정규화 — 공백·문장부호 제거 후 소문자화."""
    return re.sub(r"[\s\W_]+", "", text or "").lower()


def build_title_map():
    """booking.json(실시간 예매율 TOP 10)으로 norm제목 → (movieCd, 원제목) 맵.

    매칭 기준은 다른 체인 크롤러와 동일하게 '실시간 예매율 TOP 10' 하나로 통일.
    """
    title_map = {}
    fpath = DATA_DIR / "booking.json"
    if fpath.exists():
        try:
            doc = json.loads(fpath.read_text(encoding="utf-8"))
            for row in doc.get("bookingRate") or []:
                if row.get("movieCd") and row.get("title"):
                    title_map[norm_title(row["title"])] = (row["movieCd"],
                                                           row["title"])
        except (json.JSONDecodeError, OSError):
            pass
    return title_map


def collect_events():
    """Selenium 으로 CGV 이벤트 탭을 탐색하며 searchEvtListForPage 응답 캡처."""
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.common.by import By
    from webdriver_manager.chrome import ChromeDriverManager

    opts = Options()
    for arg in ("--headless=new", "--no-sandbox", "--disable-dev-shm-usage",
                "--window-size=1400,3000", "--log-level=3"):
        opts.add_argument(arg)
    opts.add_argument(f"user-agent={UA}")
    opts.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()), options=opts)

    events = {}
    try:
        driver.get("https://cgv.co.kr/")
        time.sleep(6)
        driver.execute_cdp_cmd("Network.enable", {
            "maxTotalBufferSize": 200_000_000,
            "maxResourceBufferSize": 100_000_000})

        # 첫 진입 팝업(모달) 닫기
        for txt in ("오늘은 그만 보기", "닫기"):
            for el in driver.find_elements(
                    By.XPATH, f"//button[contains(normalize-space(),'{txt}')]"):
                try:
                    driver.execute_script("arguments[0].click();", el)
                except Exception:
                    pass
        time.sleep(1)

        # 이벤트/혜택 탭
        tab = driver.find_elements(
            By.XPATH, "//button[normalize-space()='이벤트/혜택']")
        if not tab:
            sys.exit("CGV '이벤트/혜택' 탭을 찾지 못했습니다. (사이트 구조 변경 가능성)")
        driver.execute_script("arguments[0].click();", tab[0])
        time.sleep(8)

        # 서브탭(SPECIAL·극장·제휴) 순회 + 스크롤로 전체 페이지 로드.
        # '영화'는 메인탭과 텍스트가 겹쳐 잘못 클릭되므로 제외(기본 목록이 영화 이벤트)
        for sub in ("SPECIAL", "극장", "제휴"):
            for el in driver.find_elements(
                    By.XPATH, f"//*[normalize-space()='{sub}']"):
                try:
                    driver.execute_script("arguments[0].click();", el)
                    time.sleep(4)
                    for _ in range(10):
                        driver.execute_script(
                            "window.scrollTo(0,document.body.scrollHeight);")
                        time.sleep(1)
                    break
                except Exception:
                    pass

        # CGV JS 가 호출한 searchEvtListForPage 응답 본문을 CDP 로 캡처
        for entry in driver.get_log("performance"):
            try:
                msg = json.loads(entry["message"])["message"]
            except (json.JSONDecodeError, KeyError):
                continue
            if (msg.get("method") == "Network.responseReceived"
                    and "searchEvtListForPage"
                    in msg["params"]["response"]["url"]):
                rid = msg["params"]["requestId"]
                try:
                    body = driver.execute_cdp_cmd(
                        "Network.getResponseBody", {"requestId": rid})
                    doc = json.loads(body["body"])
                except Exception:
                    continue
                for item in (doc.get("data") or {}).get("list") or []:
                    if item.get("evntNo"):
                        events[item["evntNo"]] = item
    finally:
        driver.quit()
    return list(events.values())


def main():
    print("[*] CGV 이벤트 수집 중 (Selenium)...")
    raw = collect_events()
    if not raw:
        sys.exit("CGV 이벤트를 수집하지 못했습니다. (사이트 구조 변경 가능성)")

    title_map = build_title_map()

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

    for item in raw:
        name = (item.get("evntNm") or "").strip()
        if not name:
            continue
        ptype = classify(name)
        type_counter[ptype] += 1
        event_rec = {
            "eventId": item.get("evntNo"),
            "name": name,
            "type": ptype,
            "start": (item.get("evntStartDt") or "")[:10],
            "end": (item.get("evntEndDt") or "")[:10],
        }
        # [영화명] 파싱 → 매칭, 실패 시 이벤트명 전체로 재시도
        brackets = [b.strip() for b in re.findall(r"\[([^\[\]]+)\]", name)]
        hit = None
        for cand in brackets:
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
                "events": [],
            })
            rec["counts"][ptype] += 1
            rec["events"].append(event_rec)
        else:
            event_rec["movieName"] = brackets[0] if brackets else None
            unmatched.append(event_rec)

    out = {
        "chain": "CGV",
        "source": "CGV 이벤트 API · searchEvtListForPage (브라우저 탐색 캡처)",
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
    print(f"✓ CGV 프로모션 저장 → {OUT_FILE.relative_to(ROOT)}")
    print(f"  진행 이벤트 {len(raw)}건 · 영화 매칭 {len(out['movies'])}편 "
          f"· 미매칭 {len(unmatched)}건")
    print(f"  타입 분포: 쿠폰 {type_counter['coupon']} · "
          f"무대인사 {type_counter['stage']} · 굿즈 {type_counter['goods']} · "
          f"기타 {type_counter['etc']}")


if __name__ == "__main__":
    main()
