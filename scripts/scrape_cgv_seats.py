#!/usr/bin/env python3
"""
scrape_cgv_seats.py
--------------------------------------------------
나무위키 CGV 지점 페이지에서 관별 좌석 데이터 파싱해
`assets/data/theater_seats_cgv.json` 의 placeholder 지점(167개) 을 실제
데이터로 교체한다. 진짜 데이터(28개, placeholder 플래그 없음)는 보존.

나무위키 CGV 페이지의 좌석 표기는 두 형식이 섞여있다:
  형식 A (인라인): '2.2.1 . 1관 SCREENX (Laser): 171석'
  형식 B (문장형): '1관은 총 211석 이다'

둘 다 파싱해 합산. 파싱 실패한 지점은 placeholder 플래그 유지.
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
SEATS_FILE = ROOT / "assets" / "data" / "theater_seats_cgv.json"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# 형식 A: 'N관 ... : NNN석'  (콜론 앞 40자 이내, 특수관 이름 포함)
PAT_INLINE = re.compile(r"(\d{1,2})관[^:\d]{0,40}:\s*([\d,]{2,5})\s*석")
# 형식 A2: 'N관 - NNN석'  (관 직후 대시)
PAT_DASH = re.compile(r"(\d{1,2})관\s*-\s*([\d,]{2,5})\s*석")
# 형식 B: 'N관 ... 총 NNN석' (관~총 사이 '은 3층에 위치하며'·'IMAX 편집' 등 텍스트
# 허용). '총' 이 관 뒤에 오므로 요약행 '총 N관 X석'(총이 관 앞)·'N관 X석'(총 없음)은
# 매칭 안 됨 → 관별 좌석만 안전하게 추출.
PAT_SENTENCE = re.compile(r"(\d{1,2})관[^.]{0,22}?총\s*([\d,]{2,5})\s*석")
# 특수관 type 추출용 키워드
TYPE_KW = ("SCREENX", "IMAX", "4DX", "Laser", "LASER", "Atmos", "ATMOS",
           "GOLD", "Cine", "PRIVATE", "BEREX", "컴포트", "SWEETBOX",
           "TEMPUR", "리클라이너", "ArtHouse")


def fetch_namuwiki(branch):
    url = f"https://namu.wiki/w/{quote(f'CGV {branch}')}"
    try:
        with urlopen(Request(url, headers={
                "User-Agent": UA, "Accept-Language": "ko-KR,ko"}),
                timeout=20) as resp:
            html = resp.read().decode("utf-8", "replace")
    except (HTTPError, URLError):
        return None
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"&[a-z#0-9]+;", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text


def parse_halls(text):
    if not text:
        return []
    # 전체 텍스트 대상. (과거 '둘러보기' 이전만 잘랐으나, 페이지 상단에 접기 토글
    # 등으로 '둘러보기'가 일찍 등장하면 관별 본문이 통째로 잘려 누락됐다.
    # 좌석 패턴은 'N관 ... 총/콜론/대시 NNN석' 으로 specific 해 푸터 네비(지점명만)
    # 에는 매칭되지 않으므로 전체 텍스트를 그대로 본다.)
    section = text

    halls = {}

    def add(no_int, seats_str, ctx):
        seats = int(seats_str.replace(",", ""))
        if not (1 <= seats <= 2000):
            return
        no = f"{no_int}관"
        stype = next((kw for kw in TYPE_KW if kw in ctx), None)
        # 이미 있으면 스킵 (먼저 잡힌 게 보통 더 정확)
        if no not in halls:
            halls[no] = {"no": no, "seats": seats,
                         **({"type": stype} if stype else {})}

    # 문장형(가장 명확) → 콜론 → 대시 순으로 우선 적용
    for m in PAT_SENTENCE.finditer(section):
        add(m.group(1), m.group(2), m.group(0))
    for m in PAT_INLINE.finditer(section):
        add(m.group(1), m.group(2), m.group(0))
    for m in PAT_DASH.finditer(section):
        add(m.group(1), m.group(2), m.group(0))

    return sorted(halls.values(), key=lambda h: int(h["no"][:-1]))


def update_seats():
    if not SEATS_FILE.exists():
        sys.exit(f"파일 없음: {SEATS_FILE}")
    doc = json.loads(SEATS_FILE.read_text(encoding="utf-8"))
    theaters = doc.get("theaters") if isinstance(doc, dict) else doc

    targets = [t for t in theaters if t.get("placeholder")]
    print(f"placeholder 지점 {len(targets)}개 처리 시작 "
          f"(진짜 {len(theaters)-len(targets)}개는 보존)\n")

    updated = 0
    failed = []
    for t in targets:
        name = t.get("name", "")
        print(f"  {name:<28}", end="")
        text = fetch_namuwiki(name)
        halls = parse_halls(text) if text else []
        if not halls:
            print(" → 실패 (placeholder 유지)")
            failed.append(name)
            continue
        t["halls"] = halls
        t["total_halls"] = len(halls)
        t["total_seats"] = sum(h["seats"] for h in halls)
        t.pop("placeholder", None)
        print(f" → {len(halls)}개관 · {t['total_seats']:,}석")
        updated += 1
        time.sleep(0.3)

    doc["updatedAt"] = datetime.now(KST).isoformat(timespec="seconds")
    SEATS_FILE.write_text(json.dumps(doc, ensure_ascii=False, indent=2),
                          encoding="utf-8")
    real_now = sum(1 for t in theaters if not t.get("placeholder"))
    print(f"\n✓ 갱신 완료 · 신규 {updated}개 교체 · 실패 {len(failed)}개")
    print(f"  진짜 데이터 총 {real_now}/{len(theaters)} 지점")
    if failed:
        print(f"  실패: {', '.join(failed[:12])}"
              + (f" ... 외 {len(failed)-12}" if len(failed) > 12 else ""))


if __name__ == "__main__":
    update_seats()
