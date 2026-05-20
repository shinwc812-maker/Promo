#!/usr/bin/env python3
"""
fetch_boxoffice.py
--------------------------------------------------
KOFIC OpenAPI 의 searchDailyBoxOfficeList 를 호출해
assets/data/boxoffice.json 을 생성한다.

대시보드(assets/js/dashboard.js)는 이 JSON 을 fetch 로 읽어
박스오피스 TOP 10 패널을 그린다. (없으면 data.js 목업으로 폴백)

API 키는 다음 순서로 찾는다:
  1) 환경변수 KOFIC_API_KEY
  2) 프로젝트 루트의 .env 파일 (KOFIC_API_KEY=발급키)

사용:
  python scripts/fetch_boxoffice.py            # 어제 날짜 (기본)
  python scripts/fetch_boxoffice.py 20260515   # 특정 날짜 지정

의존성: 파이썬 표준 라이브러리만 사용 (pip install 불필요)
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

# Windows 콘솔(cp949)에서 한글 메시지가 깨지지 않도록 출력 인코딩 고정
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

KST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"
OUT_FILE = ROOT / "assets" / "data" / "boxoffice.json"
API_URL = ("https://www.kobis.or.kr/kobisopenapi/webservice/rest"
           "/boxoffice/searchDailyBoxOfficeList.json")


def load_api_key():
    """환경변수 → .env 파일 순으로 KOFIC API 키를 찾는다."""
    key = os.environ.get("KOFIC_API_KEY")
    if key:
        return key.strip()
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, _, value = line.partition("=")
            if name.strip() == "KOFIC_API_KEY":
                return value.strip().strip('"').strip("'")
    return None


def fmt_change(item):
    """전일 대비 관객수 증감을 대시보드 표기 형식으로 변환."""
    if item.get("rankOldAndNew") == "NEW":
        return "NEW"
    try:
        pct = float(item.get("audiChange", "0"))
    except ValueError:
        return "—"
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct:.1f}%"


def main():
    key = load_api_key()
    if not key:
        sys.exit(
            "KOFIC_API_KEY 를 찾을 수 없습니다.\n"
            "프로젝트 루트에 .env 파일을 만들고 아래 형태로 키를 넣어주세요:\n"
            "  KOFIC_API_KEY=발급받은키\n"
            "(.env.example 참고 · 키 발급: https://www.kobis.or.kr/kobisopenapi)"
        )

    # 대상 날짜: 인자 없으면 어제 (박스오피스는 전일자까지만 집계됨)
    if len(sys.argv) > 1:
        target_dt = sys.argv[1]
        if not (len(target_dt) == 8 and target_dt.isdigit()):
            sys.exit(f"날짜 형식이 잘못됐습니다: '{target_dt}' (YYYYMMDD 형태로 입력)")
    else:
        target_dt = (datetime.now(KST) - timedelta(days=1)).strftime("%Y%m%d")

    params = urlencode({"key": key, "targetDt": target_dt, "itemPerPage": "10"})
    url = f"{API_URL}?{params}"

    try:
        with urlopen(url, timeout=20) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except (HTTPError, URLError) as exc:
        sys.exit(f"KOFIC API 호출 실패: {exc}")
    except json.JSONDecodeError as exc:
        sys.exit(f"KOFIC 응답 파싱 실패: {exc}")

    # 키 오류 등은 faultInfo 로 내려옴
    if "faultInfo" in payload:
        fault = payload["faultInfo"]
        sys.exit(f"KOFIC API 오류: {fault.get('message')} ({fault.get('errorCode')})")

    result = payload.get("boxOfficeResult", {})
    rows = result.get("dailyBoxOfficeList", [])
    if not rows:
        sys.exit(f"{target_dt} 박스오피스 데이터가 비어 있습니다. (날짜 확인 필요)")

    box_office = [
        {
            "rank": int(item["rank"]),
            "movieCd": item["movieCd"],
            "title": item["movieNm"],
            "audience": int(item["audiCnt"]),
            "change": fmt_change(item),
        }
        for item in rows
    ]

    out = {
        "source": "KOFIC OpenAPI · searchDailyBoxOfficeList",
        "targetDt": target_dt,
        "showRange": result.get("showRange", ""),
        "fetchedAt": datetime.now(KST).isoformat(timespec="seconds"),
        "boxOffice": box_office,
    }

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"✓ {target_dt} 박스오피스 {len(box_office)}건 저장 "
          f"→ {OUT_FILE.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
