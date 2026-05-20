#!/usr/bin/env python3
"""
fetch_booking.py
--------------------------------------------------
KOBIS 실시간 예매율 페이지(findRealTicketList.do)를 스크래핑해
assets/data/booking.json 을 생성한다.

실시간 예매율은 KOFIC OpenAPI 에 엔드포인트가 없어 페이지를 직접
파싱한다. 다행히 데이터가 서버 렌더링된 HTML 표로 내려오므로
브라우저 없이 표준 라이브러리만으로 수집할 수 있다.

delta(직전 대비 예매율 변화)는 이전에 저장해 둔 booking.json 과
movieCd 기준으로 비교해 계산한다. → 15~60분 주기로 돌리면
시간대별 예매율 증감이 표시된다. (첫 실행은 비교 대상이 없어 '—')

사용:
  python scripts/fetch_booking.py

의존성: 파이썬 표준 라이브러리만 사용 (pip install · API 키 불필요)
"""
import json
import os
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
ENV_FILE = ROOT / ".env"
OUT_FILE = ROOT / "assets" / "data" / "booking.json"
PAGE_URL = (
    "https://www.kobis.or.kr/kobis/business/stat/boxs/findRealTicketList.do"
    "?loadEnd=0&repNationCd=&areaCd=&dmlMode=search&allMovieYn=Y"
)
MOVIE_INFO_URL = ("https://www.kobis.or.kr/kobisopenapi/webservice/rest"
                  "/movie/searchMovieInfo.json")
TOP_N = 10
# 페이지 인코딩 — 응답 헤더(charset=UTF-8) 및 바이트 검증 결과 모두 UTF-8
PAGE_ENCODING = "utf-8"


def load_api_key():
    """KOFIC API 키 — 환경변수 → .env 순. (장르 조회용, 없으면 장르 생략)"""
    key = os.environ.get("KOFIC_API_KEY")
    if key:
        return key.strip()
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("KOFIC_API_KEY") and "=" in line:
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def fetch_genre(key, movie_cd):
    """KOFIC searchMovieInfo 로 장르 문자열 반환 (예: '액션, 스릴러'). 실패 시 ''."""
    if not key or not movie_cd:
        return ""
    url = f"{MOVIE_INFO_URL}?{urlencode({'key': key, 'movieCd': movie_cd})}"
    try:
        with urlopen(url, timeout=15) as resp:
            doc = json.loads(resp.read().decode("utf-8"))
        info = doc.get("movieInfoResult", {}).get("movieInfo", {})
        genres = [g.get("genreNm") for g in info.get("genres", []) if g.get("genreNm")]
        return ", ".join(genres)
    except (HTTPError, URLError, json.JSONDecodeError, KeyError):
        return ""


class RealTicketParser(HTMLParser):
    """findRealTicketList.do 응답의 데이터 표(<tr id="tr_">)를 파싱."""

    def __init__(self):
        super().__init__()
        self.rows = []          # [(cells, movie_cd), ...]
        self._in_row = False
        self._in_td = False
        self._cells = []
        self._buf = []
        self._movie_cd = None

    def handle_starttag(self, tag, attrs):
        attr = dict(attrs)
        if tag == "tr" and attr.get("id") == "tr_":
            self._in_row = True
            self._cells = []
            self._movie_cd = None
        elif tag == "td" and self._in_row:
            self._in_td = True
            self._buf = []
        elif tag == "a" and self._in_row:
            # 영화명 링크: onclick="mstView('movie','20259626');..."
            match = re.search(r"mstView\('movie','(\d+)'\)", attr.get("onclick", ""))
            if match:
                self._movie_cd = match.group(1)

    def handle_data(self, data):
        if self._in_td:
            self._buf.append(data)

    def handle_endtag(self, tag):
        if tag == "td" and self._in_td:
            self._in_td = False
            self._cells.append("".join(self._buf).strip())
        elif tag == "tr" and self._in_row:
            self._in_row = False
            if len(self._cells) >= 7:
                self.rows.append((self._cells, self._movie_cd))


def to_int(text):
    digits = re.sub(r"[^\d-]", "", text)
    return int(digits) if digits not in ("", "-") else 0


def to_rate(text):
    """'46.6%' → 46.6 (퍼센트·콤마 등 제거)"""
    num = re.sub(r"[^\d.]", "", text)
    return round(float(num), 1) if num else 0.0


def load_prev_rates():
    """직전 booking.json 의 movieCd→예매율 맵 (delta 계산용)."""
    if not OUT_FILE.exists():
        return {}
    try:
        prev = json.loads(OUT_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return {
        item["movieCd"]: item["rate"]
        for item in prev.get("bookingRate", [])
        if item.get("movieCd")
    }


def main():
    request = Request(PAGE_URL, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urlopen(request, timeout=25) as resp:
            raw = resp.read()
    except (HTTPError, URLError) as exc:
        sys.exit(f"KOBIS 실시간 예매율 페이지 요청 실패: {exc}")

    parser = RealTicketParser()
    parser.feed(raw.decode(PAGE_ENCODING, errors="replace"))

    if not parser.rows:
        sys.exit("실시간 예매율 데이터를 찾지 못했습니다. "
                 "(페이지 구조 변경 또는 일시적 빈 응답 가능성)")

    prev_rates = load_prev_rates()
    api_key = load_api_key()
    genre_cache = {}   # movieCd → 장르 (중복 호출 방지)

    booking = []
    for cells, movie_cd in parser.rows[:TOP_N]:
        # cells: [순위, 영화명, 개봉일, 예매율, 예매매출액, 누적매출액, 예매관객수, 누적관객수]
        rate = to_rate(cells[3])
        if movie_cd and movie_cd in prev_rates:
            diff = rate - prev_rates[movie_cd]
            delta = f"{diff:+.1f}"
        else:
            delta = "NEW" if prev_rates else "—"
        if movie_cd and movie_cd not in genre_cache:
            genre_cache[movie_cd] = fetch_genre(api_key, movie_cd)
        booking.append({
            "rank": to_int(cells[0]),
            "movieCd": movie_cd or "",
            "title": cells[1],
            "openDt": cells[2],
            "rate": rate,
            "audience": to_int(cells[6]),   # 예매관객수
            "delta": delta,
            "genre": genre_cache.get(movie_cd, ""),
        })

    out = {
        "source": "KOBIS 실시간 예매율 · findRealTicketList.do",
        "fetchedAt": datetime.now(KST).isoformat(timespec="seconds"),
        "bookingRate": booking,
    }
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"✓ 실시간 예매율 {len(booking)}건 저장 → {OUT_FILE.relative_to(ROOT)}")
    print(f"  1위 {booking[0]['title']} {booking[0]['rate']}%")


if __name__ == "__main__":
    main()
