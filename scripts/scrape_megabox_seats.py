#!/usr/bin/env python3
"""
scrape_megabox_seats.py
--------------------------------------------------
나무위키 메가박스 지점 페이지에서 관별 좌석 데이터 파싱해
`assets/data/theater_seats_megabox.json` 의 가짜 데이터(한 지점 내 모든 관
동일 좌석) 를 실제 데이터로 교체한다.

문제 배경:
  기존 theater_seats_megabox.json 은 Gemini 가 만든 데이터인데, 한 지점의
  total_seats 를 total_halls 로 단순 나눠 모든 관에 동일 좌석을 적용했다.
  예: 코엑스 18관 모두 187석 (실제는 8~431석 다양). 결과적으로 무대인사
  좌석 합산이 부정확.

방법:
  나무위키 `메가박스 {지점명}` 페이지에는 '상영관' 섹션에 관별 좌석이
  '4.X . [관이름] : NNN석' 형태로 정리돼있다. regex 로 파싱.

  매칭 패턴 (우선순위):
    1. 숫자관 - 패턴 'N관 ... : NNN석'
    2. 특수관 - 패턴 'Dolby Cinema / MX4D / IMAX ... : NNN석'

  파싱 실패한 지점은 placeholder 플래그만 명시하고 기존 데이터 유지.
"""
import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

KST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parent.parent
SEATS_FILE = ROOT / "assets" / "data" / "theater_seats_megabox.json"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# 무대인사 사용 우선순위 지점 (먼저 처리해 확실히 진짜 데이터로 교체)
PRIORITY_BRANCHES = ("코엑스", "상암월드컵경기장", "목동")

# 특수관 이름 정규화 (포스터에 자주 쓰이는 이름 → 나무위키 표기)
SPECIAL_HALLS = (
    "Dolby Cinema",
    "Dolby Vision Atmos",
    "Dolby Vision+Atmos",
    "MX4D",
    "MEGA|LED",
    "IMAX",
    "SOUNDX",
    "THE BOUTIQUE",
    "수트 PRIVATE",
    "LE RECLINER",
)


def fetch_namuwiki(branch):
    """나무위키 `메가박스 {branch}` 페이지 HTML → 정리된 텍스트 반환."""
    url = f"https://namu.wiki/w/{quote(f'메가박스 {branch}')}"
    try:
        with urlopen(Request(url, headers={
                "User-Agent": UA,
                "Accept-Language": "ko-KR,ko"}), timeout=20) as resp:
            html = resp.read().decode("utf-8", "replace")
    except (HTTPError, URLError):
        return None
    # 태그·엔티티 제거 후 공백 정규화
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"&[a-z#0-9]+;", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text


def parse_halls(text, branch):
    """페이지 텍스트에서 관별 좌석 추출. [{no, seats, type}] 리스트."""
    if not text:
        return []
    # '상영관' 섹션 찾기 — 좌석 데이터가 시작되는 위치
    pos = text.find("상영관")
    if pos < 0:
        return []
    # 상영관 섹션부터 본문(개요/역사 등) 사이 슬라이스
    section_end = text.find("부대시설", pos)
    if section_end < 0:
        section_end = text.find("교통", pos)
    if section_end < 0:
        section_end = pos + 5000
    section = text[pos:section_end]

    halls = {}
    # 패턴 1: 'N관 ... : NNN석' (일반관 + 특수관 묶음 표기 - 'MEGA|LED 2관: 431석')
    for m in re.finditer(r"(\d{1,2})관[^:]{0,100}:\s*([\d,]{2,5})\s*석", section):
        no = f"{m.group(1)}관"
        seats = int(m.group(2).replace(",", ""))
        if 1 <= seats <= 2000:  # 합리적 범위
            # type 추출 (관 번호 앞의 특수관 키워드)
            ctx = m.group(0)
            stype = None
            for kw in ("MEGA|LED", "MX4D", "Dolby Cinema", "IMAX",
                       "SOUNDX", "리클라이너", "마이어"):
                if kw in ctx:
                    stype = kw
                    break
            halls[no] = {"no": no, "seats": seats, **({"type": stype} if stype else {})}

    # 패턴 2: 특수관 별도 라인 (예: 'Dolby Cinema Laser : 378석' — 관 번호 없음)
    # 보통 첫 번째 항목 = 1관 인 경우가 많으므로, halls 에 '1관' 없고 첫 항목이 특수관이면 1관으로 등록
    if "1관" not in halls:
        m = re.search(
            r"4\.1\s*\.\s*([^:]{1,80}?)\s*:\s*([\d,]{2,5})\s*석", section)
        if m:
            name = m.group(1).strip()
            seats = int(m.group(2).replace(",", ""))
            if 1 <= seats <= 2000:
                halls["1관"] = {"no": "1관", "seats": seats, "type": name[:50]}

    return list(halls.values())


def update_seats():
    if not SEATS_FILE.exists():
        sys.exit(f"파일 없음: {SEATS_FILE}")
    doc = json.loads(SEATS_FILE.read_text(encoding="utf-8"))
    theaters = doc.get("theaters") if isinstance(doc, dict) else doc

    updated = 0
    failed = []
    for t in theaters:
        name = t.get("name", "")
        is_priority = name in PRIORITY_BRANCHES
        prefix = "★" if is_priority else " "
        print(f"  {prefix} {name:<30}", end="")
        text = fetch_namuwiki(name)
        if not text:
            print(" → fetch 실패")
            failed.append(name)
            t["placeholder"] = True
            continue
        halls = parse_halls(text, name)
        if not halls:
            print(" → 좌석 파싱 실패")
            failed.append(name)
            t["placeholder"] = True
            continue
        # 가짜 데이터 식별 — 한 지점 내 모든 관 동일 좌석이면 placeholder
        seat_vals = [h["seats"] for h in t.get("halls", [])]
        was_placeholder = len(set(seat_vals)) <= 1 and len(seat_vals) > 1
        # 교체
        t["halls"] = halls
        t["total_halls"] = len(halls)
        t["total_seats"] = sum(h["seats"] for h in halls)
        t.pop("placeholder", None)
        new_total = t["total_seats"]
        diff = "*" if was_placeholder else ""
        print(f" → {len(halls)}개관 · {new_total:,}석 {diff}")
        updated += 1
        time.sleep(0.3)  # 나무위키 부담 줄이기

    doc["updatedAt"] = datetime.now(KST).isoformat(timespec="seconds")
    doc["source"] = "나무위키 메가박스 지점 페이지 (자동 파싱)"
    SEATS_FILE.write_text(json.dumps(doc, ensure_ascii=False, indent=2),
                          encoding="utf-8")
    print(f"\n✓ 갱신 완료 · 진짜 데이터 {updated} 지점 · 파싱 실패 {len(failed)}")
    if failed:
        print(f"  실패(placeholder 유지): {', '.join(failed[:10])}"
              + (f" ... 외 {len(failed)-10}" if len(failed) > 10 else ""))


if __name__ == "__main__":
    update_seats()
