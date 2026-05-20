#!/usr/bin/env python3
"""
extract_backdata.py
--------------------------------------------------
대시보드가 화면에 보여주는 숫자의 "백데이터(보고서 근거)"를 추출한다.

대시보드 매트릭스(assets/js/dashboard.js)와 동일한 기준으로
  - 척추(spine) = 실시간 예매율 TOP 10 (booking.json)
  - 각 영화를 movieCd 로 박스오피스(boxoffice.json) · 4사 프로모션
    (promotions_{cgv,lotte,megabox,cineq}.json) 과 조인
한 다음, long format 으로 (1) 로컬 CSV 누적 + (2) 구글 시트 누적 한다.

산출물:
  (1) assets/data/backdata/promotions_daily.csv  (로컬 백업 · utf-8-sig BOM)
  (2) 구글 시트 (Apps Script 웹앱 · .env SHEETS_WEBAPP_URL 설정 시)
  - grain(행 단위) = (date, movieCd, chain)  · 영화 1편당 4사 4행
  - 같은 date 를 다시 추출하면 그 날짜 행만 교체(upsert)해 중복 안 쌓임
    (CSV·시트 모두 동일하게 날짜 기준 upsert)

영화 단위 집계값(promoSeatsTotal · seatRatioPct · efficiency)은 같은 영화의
4개 체인 행에 동일하게 들어간다(denormalize). 한 행만 봐도 맥락을 알 수 있고,
피벗으로 SUM(promoSeats) 해도 합산이 맞도록 promoSeats 는 체인별 실수치다.

의존성: 파이썬 표준 라이브러리만 사용 (pip install 불필요)
사용:
  python scripts/extract_backdata.py
"""
import csv
import json
import os
import sys
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
OUT_DIR = DATA_DIR / "backdata"
OUT_FILE = OUT_DIR / "promotions_daily.csv"

# 체인 키(JSON 파일) → 라벨(대시보드 표기와 동일)
CHAINS = [
    ("cgv", "CGV", "promotions_cgv.json"),
    ("lotte", "LOTTE", "promotions_lotte.json"),
    ("megabox", "MEGA", "promotions_megabox.json"),
    ("cineq", "CINEQ", "promotions_cineq.json"),
]

FIELDS = [
    "date",            # 수집일 (KST, YYYY-MM-DD)
    "title",
    "chain",           # CGV / LOTTE / MEGA / CINEQ
    "bookingRate",     # 예매율 (%)
    "bookingAudi",     # 예매 관객수 (누적)
    "stageEvt",        # 해당 체인 무대인사 건수
    "stageSeats",      # 해당 체인 무대인사·시사회·GV 좌석수
    "couponEvt",       # 해당 체인 쿠폰 건수
    "couponIssued",    # 해당 체인 쿠폰 발행 매수
    "goodsEvt",        # 해당 체인 굿즈 건수
    "promoTotal",      # 4사 합산 프로모션 좌석 = 무대인사좌석 + 쿠폰매수 (영화 단위)
    "promoRatioPct",   # 프로모션좌석합계/예매관객 ×100 (대시보드 지표, 영화 단위)
]

# CSV 헤더용 한글 라벨 (코드 로직은 위 영어 키를 쓰고, 출력 헤더만 한글)
FIELD_KR = {
    "date": "날짜",
    "title": "영화제목",
    "chain": "영화관",
    "bookingRate": "예매율(%)",
    "bookingAudi": "예매관객수",
    "stageSeats": "무대인사·시사회좌석수",
    "couponIssued": "쿠폰매수",
    "stageEvt": "무대인사건수",
    "couponEvt": "쿠폰건수",
    "goodsEvt": "굿즈건수",
    "promoTotal": "프로모션좌석합계",
    "promoRatioPct": "프로모션좌석점유율(%)",
}


def load_json(name):
    path = DATA_DIR / name
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def load_env(key):
    """환경변수 → 프로젝트 루트 .env 순으로 값을 찾는다."""
    val = os.environ.get(key)
    if val:
        return val.strip()
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, _, value = line.partition("=")
            if name.strip() == key:
                return value.strip().strip('"').strip("'")
    return None


def post_to_sheets(today, header, today_rows):
    """오늘자 행을 구글 시트(Apps Script 웹앱)로 전송해 누적 저장한다.

    웹앱(scripts/sheets_webapp.gs)이 같은 날짜 행을 교체(upsert)한다.
    SHEETS_WEBAPP_URL 미설정이면 조용히 건너뛴다(설정 전엔 CSV 만 누적).
    """
    url = load_env("SHEETS_WEBAPP_URL")
    if not url:
        print("  (구글 시트 미설정 — .env 의 SHEETS_WEBAPP_URL 없음 · 시트 전송 생략)")
        return
    payload = json.dumps({
        "token": load_env("SHEETS_TOKEN") or "",
        "date": today,
        "header": header,
        "rows": today_rows,
    }, ensure_ascii=False).encode("utf-8")
    req = Request(url, data=payload,
                  headers={"Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=30) as r:
            resp = json.loads(r.read().decode("utf-8"))
    except (HTTPError, URLError, json.JSONDecodeError) as exc:
        print(f"  ⚠ 구글 시트 전송 실패: {exc}")
        return
    if resp.get("ok"):
        print(f"  ✓ 구글 시트 누적 → {today} {resp.get('added')}행")
    else:
        print(f"  ⚠ 구글 시트 오류: {resp.get('error')}")


def main():
    booking = load_json("booking.json")
    if not booking or not booking.get("bookingRate"):
        sys.exit("booking.json 이 없거나 비어 있습니다. fetch_booking.py 를 먼저 실행하세요.")

    # 체인별 movieCd → movie 레코드 인덱스
    chain_idx = {}
    for key, _label, fname in CHAINS:
        doc = load_json(fname) or {}
        chain_idx[key] = {m["movieCd"]: m for m in doc.get("movies", [])}

    spine = booking["bookingRate"]
    today = datetime.now(KST).strftime("%Y-%m-%d")

    def chain_seats(cd, key):
        """체인의 무대인사·시사회·GV 좌석수 (promoSeats)."""
        m = chain_idx[key].get(cd)
        return (m.get("promoSeats", 0) if m else 0)

    def chain_coupon_issued(cd, key):
        """체인의 쿠폰 발행 매수 합계 (issued 있는 coupon 이벤트만)."""
        m = chain_idx[key].get(cd)
        if not m:
            return 0
        return sum((e.get("issued") or 0) for e in m.get("events", [])
                   if e.get("type") == "coupon")

    # 영화 단위 4사 합산 프로모션 좌석 = 무대인사 좌석 + 쿠폰 매수 (굿즈 제외)
    promo_total_by_cd = {
        bk["movieCd"]: sum(chain_seats(bk["movieCd"], k)
                           + chain_coupon_issued(bk["movieCd"], k)
                           for k, _l, _f in CHAINS)
        for bk in spine
    }

    # ── long format 행 생성 ────────────────────────────────────────────
    rows = []
    for bk in spine:
        cd = bk["movieCd"]
        rate = float(bk.get("rate") or 0)
        audi = int(bk.get("audience") or 0)
        promo_total = promo_total_by_cd[cd]
        promo_ratio = round((promo_total / audi) * 100, 1) if audi else ""

        for key, label, _f in CHAINS:
            m = chain_idx[key].get(cd)
            counts = m.get("counts", {}) if m else {}
            rows.append({
                "date": today,
                "title": bk.get("title", ""),
                "chain": label,
                "bookingRate": rate,
                "bookingAudi": audi,
                "stageSeats": chain_seats(cd, key),
                "couponIssued": chain_coupon_issued(cd, key),
                "stageEvt": counts.get("stage", 0),
                "couponEvt": counts.get("coupon", 0),
                "goodsEvt": counts.get("goods", 0),
                "promoTotal": promo_total,
                "promoRatioPct": promo_ratio,
            })

    # ── 마스터 CSV upsert (오늘 날짜 행 교체 후 누적) ──────────────────
    # 기존 파일은 헤더 텍스트(한글/영어)와 무관하게 위치 기반으로 읽어
    # 영어 키 dict 로 복원한다 → 헤더를 한글로 바꿔도 안전하게 누적된다.
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    existing = []
    if OUT_FILE.exists():
        with OUT_FILE.open(encoding="utf-8-sig", newline="") as fh:
            reader = csv.reader(fh)
            next(reader, None)  # 헤더 행 건너뜀
            for raw in reader:
                if not raw:
                    continue
                rec = dict(zip(FIELDS, raw))
                if rec.get("date") != today:
                    existing.append(rec)

    merged = existing + rows
    # 정렬: 날짜 내림차순 → 예매율 내림차순(=순위 오름차순) → 체인 순서
    chain_order = {label: i for i, (_k, label, _f) in enumerate(CHAINS)}

    def sort_key(r):
        try:
            rate = float(r.get("bookingRate") or 0)
        except (TypeError, ValueError):
            rate = 0
        return (r.get("date", ""), rate, -chain_order.get(r.get("chain"), 99))

    merged.sort(key=sort_key, reverse=True)

    with OUT_FILE.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow([FIELD_KR[f] for f in FIELDS])  # 한글 헤더
        for r in merged:
            writer.writerow([r.get(f, "") for f in FIELDS])

    days = len({r.get("date") for r in merged})
    print(f"✓ 백데이터 추출 → {OUT_FILE.relative_to(ROOT)}")
    print(f"  오늘({today}) {len(rows)}행 갱신 · 누적 {len(merged)}행 / {days}일치")
    matched = sum(1 for bk in spine
                  if any(chain_idx[k].get(bk['movieCd']) for k, _l, _f in CHAINS))
    print(f"  예매율 TOP{len(spine)} 중 4사 프로모션 매칭 {matched}편")

    # 구글 시트 누적 (Apps Script 웹앱 · 미설정이면 생략)
    header = [FIELD_KR[f] for f in FIELDS]
    today_rows = [[r.get(f, "") for f in FIELDS] for r in rows]
    post_to_sheets(today, header, today_rows)


if __name__ == "__main__":
    main()
