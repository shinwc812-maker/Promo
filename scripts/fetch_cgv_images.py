#!/usr/bin/env python3
"""
fetch_cgv_images.py
--------------------------------------------------
CGV 진행중 이벤트의 상세페이지 포스터 이미지를 수집한다.

CGV 이벤트 API(searchEvtListForPage)는 x-signature 서명을 요구해 외부 직접
호출이 불가하다. 그래서 실제 Chrome(Selenium)으로 CGV 이벤트 탭을 정상
탐색하면 CGV 자기 JS 가 서명해 목록을 불러온다. 그 응답을 CDP 로 캡처해
진행중 이벤트(evntNo)를 모은 뒤, 각 이벤트 상세페이지를 렌더해 포스터
이미지를 내려받는다. (서명 위조가 아니라 정상 브라우저로 접속)

종료된 이벤트 제외: 목록 API 가 expnYn=N(미종료)으로 응답 → 진행중만 수집.

산출물:
  - assets/data/cgv_images/{evntNo}.jpg  : 이벤트 상세 포스터 이미지
  - assets/data/cgv_images/_pending.json : 수집 목록 (evntNo·제목·기간·경로)
    → Claude 가 이미지를 분석해 promotions_cgv.json 을 만든다.

의존성: selenium, webdriver-manager (+ 로컬 Chrome)
"""
import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

KST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "assets" / "data"
IMG_DIR = DATA_DIR / "cgv_images"
PENDING_FILE = IMG_DIR / "_pending.json"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
DETAIL_URL = "https://cgv.co.kr/evt/eventDetail?evntNo="


def make_driver():
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from webdriver_manager.chrome import ChromeDriverManager

    opts = Options()
    for arg in ("--headless=new", "--no-sandbox", "--disable-dev-shm-usage",
                "--window-size=1400,3000", "--log-level=3"):
        opts.add_argument(arg)
    opts.add_argument(f"user-agent={UA}")
    opts.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    return webdriver.Chrome(
        service=Service(ChromeDriverManager().install()), options=opts)


def enumerate_events(driver):
    """CGV 이벤트 탭을 탐색해 진행중 이벤트 {evntNo: 이벤트정보} 수집."""
    from selenium.webdriver.common.by import By

    driver.get("https://cgv.co.kr/")
    time.sleep(6)
    driver.execute_cdp_cmd("Network.enable", {
        "maxTotalBufferSize": 200_000_000,
        "maxResourceBufferSize": 100_000_000})

    events = {}
    # 홈페이지 featured 이벤트 evntNo (극장 카테고리 무대인사 등 포함)
    home_nos = set(re.findall(r'evntNo[=\\":]+(\d+)', driver.page_source))

    # 첫 진입 팝업 닫기
    for txt in ("오늘은 그만 보기", "닫기"):
        for el in driver.find_elements(
                By.XPATH, f"//button[contains(normalize-space(),'{txt}')]"):
            try:
                driver.execute_script("arguments[0].click();", el)
            except Exception:
                pass
    time.sleep(1)

    # 이벤트/혜택 탭 진입
    tab = driver.find_elements(
        By.XPATH, "//button[normalize-space()='이벤트/혜택']")
    if tab:
        driver.execute_script("arguments[0].click();", tab[0])
        time.sleep(8)
        def scroll_to_bottom(rounds=25):
            """페이지 높이가 더 이상 안 늘 때까지 스크롤 — 지연 로딩/페이징 전체 로드."""
            last = 0
            for _ in range(rounds):
                driver.execute_script(
                    "window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(1.3)
                height = driver.execute_script(
                    "return document.body.scrollHeight")
                if height == last:
                    break
                last = height

        def click_sub_subs():
            """현재 카테고리의 linetabMini 하위 sub-sub-tab 을 모두 순회.
            영화 카테고리는 전체/일반/시사회/무대인사/아트하우스 sub-sub-tab 이 있고,
            각각 별도의 evntCtgryLclsCd 로 API 가 호출됨 (무대인사=03·시사회=02·아트하우스=06 등)."""
            # 탭이 보이도록 상단으로
            driver.execute_script("window.scrollTo(0, 0);")
            time.sleep(0.6)
            labels = driver.execute_script(
                "return Array.from(document.querySelectorAll("
                "'button[class*=linetabMini]'))"
                ".map(e=>(e.innerText||'').trim()).filter(t=>t.length>0)")
            for txt in list(dict.fromkeys(labels)):
                btns = driver.find_elements(By.XPATH,
                    f"//button[contains(@class,'linetabMini') and "
                    f"normalize-space()='{txt}']")
                if not btns:
                    continue
                try:
                    driver.execute_script(
                        "arguments[0].scrollIntoView({block:'center'});",
                        btns[0])
                    time.sleep(0.4)
                    driver.execute_script("arguments[0].click();", btns[0])
                    time.sleep(4)
                    scroll_to_bottom()
                    driver.execute_script("window.scrollTo(0, 0);")
                    time.sleep(0.4)
                except Exception:
                    pass

        def click_roundtab(text):
            btns = driver.find_elements(
                By.XPATH,
                f"//button[contains(@class,'roundtab') and "
                f"normalize-space()='{text}']")
            if not btns:
                return False
            try:
                driver.execute_script(
                    "arguments[0].scrollIntoView({block:'center'});", btns[0])
                time.sleep(0.4)
                driver.execute_script("arguments[0].click();", btns[0])
                time.sleep(4)
                return True
            except Exception:
                return False

        scroll_to_bottom()
        # 영화 roundtab 명시 클릭 → sub-sub-tab(전체/일반/시사회/무대인사/아트하우스) 활성화 보장
        click_roundtab("영화")
        scroll_to_bottom()
        click_sub_subs()
        # 나머지 상위 roundtab 순회 + 각 카테고리의 sub-sub-tab 도 순회
        for sub in ("SPECIAL", "극장", "제휴", "멤버십/CLUB"):
            if click_roundtab(sub):
                scroll_to_bottom()
                click_sub_subs()

    # CGV JS 가 호출한 searchEvtListForPage 응답을 CDP 로 캡처
    for entry in driver.get_log("performance"):
        try:
            msg = json.loads(entry["message"])["message"]
        except (json.JSONDecodeError, KeyError):
            continue
        if (msg.get("method") == "Network.responseReceived"
                and "searchEvtListForPage"
                in msg["params"]["response"]["url"]):
            try:
                body = driver.execute_cdp_cmd(
                    "Network.getResponseBody",
                    {"requestId": msg["params"]["requestId"]})
                doc = json.loads(body["body"])
            except Exception:
                continue
            for item in (doc.get("data") or {}).get("list") or []:
                no = item.get("evntNo")
                if no:
                    events[str(no)] = {
                        "evntNo": str(no),
                        "title": (item.get("evntNm") or "").strip(),
                        "start": (item.get("evntStartDt") or "")[:10],
                        "end": (item.get("evntEndDt") or "")[:10],
                    }
    # 목록 API 에 없던 홈 featured evntNo 보강
    for no in home_nos:
        events.setdefault(no, {"evntNo": no, "title": "", "start": "", "end": ""})
    return list(events.values())


def main():
    print("[*] CGV 진행중 이벤트 수집 중 (Selenium)...")
    driver = make_driver()
    pending = []
    try:
        events = enumerate_events(driver)
        if not events:
            sys.exit("CGV 이벤트를 찾지 못했습니다. (사이트 구조 변경 가능성)")
        print(f"  진행중 이벤트 {len(events)}건 — 상세페이지 이미지 수집 시작")
        IMG_DIR.mkdir(parents=True, exist_ok=True)

        for idx, ev in enumerate(events, 1):
            no = ev["evntNo"]
            try:
                driver.get(DETAIL_URL + no)
                time.sleep(4)
            except Exception as exc:
                print(f"  [{idx}/{len(events)}] {no}: 상세 로드 실패 ({exc})")
                continue
            title = ev["title"] or (driver.title or "").replace("| CGV", "").strip()
            srcs = driver.execute_script(
                "return Array.from(document.querySelectorAll('img'))"
                ".map(i=>i.currentSrc||i.src)")
            poster = next((s for s in srcs if s and "/ips/evnt/" in s), None)
            if not poster:
                print(f"  [{idx}/{len(events)}] {no}: 포스터 이미지 없음 (스킵)")
                continue
            try:
                blob = urlopen(Request(poster, headers={"User-Agent": UA}),
                               timeout=20).read()
            except (HTTPError, URLError) as exc:
                print(f"  [{idx}/{len(events)}] {no}: 이미지 다운로드 실패 ({exc})")
                continue
            (IMG_DIR / f"{no}.jpg").write_bytes(blob)
            pending.append({
                "evntNo": no,
                "title": title,
                "start": ev["start"],
                "end": ev["end"],
                "imagePath": f"assets/data/cgv_images/{no}.jpg",
                "posterUrl": poster,
            })
            print(f"  [{idx}/{len(events)}] ✓ {no} · {title[:40]}")
    finally:
        driver.quit()

    PENDING_FILE.write_text(json.dumps({
        "fetchedAt": datetime.now(KST).isoformat(timespec="seconds"),
        "count": len(pending),
        "events": pending,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✓ CGV 이벤트 이미지 {len(pending)}건 저장 → {IMG_DIR.relative_to(ROOT)}")
    print(f"  목록: {PENDING_FILE.relative_to(ROOT)} "
          f"(다음 단계: Claude 가 이미지 분석 → promotions_cgv.json)")


if __name__ == "__main__":
    main()
