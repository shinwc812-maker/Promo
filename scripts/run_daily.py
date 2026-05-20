#!/usr/bin/env python3
"""
run_daily.py
--------------------------------------------------
매일 오전 7시 (Windows Task Scheduler 트리거) 자동 실행되는 오케스트레이터.

실행 순서 (의존성 + 소요시간 고려):
  1. fetch_boxoffice.py     ~5초  (KOFIC OpenAPI)
  2. fetch_booking.py       ~5초  (KOBIS HTML scrape)
  3. fetch_promotions_lotte.py    ~30초 (LCWS API 직접 — 일정·좌석 자동)
  4. fetch_promotions_megabox.py  ~1분  (HTML scrape + 이미지 다운로드)
  5. fetch_promotions_cineq.py    ~2분  (HTML scrape + 이미지 다운로드, 페이징 ~450건)
  6. fetch_cgv_images.py    ~20분 (Selenium + CDP, sub-sub-tab 순회)
  7. build_promotions_cgv.py      ~5초  (CGV _pending.json 조립)
  8. extract_backdata.py    ~1초  (4사+박스오피스+예매율 조인 → 마스터 CSV 누적)

산출물:
  - assets/data/daily_log/{YYYY-MM-DD}.json : 실행 결과 + 신규 stage 이벤트 리스트
  - 각 체인 promotions_*.json 갱신
  - assets/data/backdata/promotions_daily.csv : 보고서 근거용 백데이터 누적

신규 stage 이벤트 감지:
  promotions_*.json 의 events 중 type=stage 이면서 screenings 가 비어있거나
  seats=0 인 것 → LLM 일정 판독이 필요한 항목 (해당 체인 SKILL.md 가이드 참조).
"""
import json
import subprocess
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
LOG_DIR = DATA_DIR / "daily_log"

# 실행 단계 — (label, [args...], 예상 소요)
STEPS = [
    ("BOXOFFICE", ["scripts/fetch_boxoffice.py"]),
    ("BOOKING",   ["scripts/fetch_booking.py"]),
    ("LOTTE",     ["scripts/fetch_promotions_lotte.py"]),
    ("MEGABOX",   ["scripts/fetch_promotions_megabox.py"]),
    ("CINEQ",     ["scripts/fetch_promotions_cineq.py"]),
    ("CGV-IMG",   ["scripts/fetch_cgv_images.py"]),
    ("CGV-BUILD", ["scripts/build_promotions_cgv.py"]),
    ("EXTRACT",   ["scripts/extract_backdata.py"]),
]


def run_step(label, args):
    """한 스크립트 실행 — stdout/stderr 캡처, 소요시간 측정."""
    print(f"\n{'='*60}")
    print(f"[{label}] 실행 시작")
    print(f"{'='*60}")
    started = datetime.now(KST)
    try:
        proc = subprocess.run(
            [sys.executable, *args],
            cwd=ROOT, capture_output=True, text=True,
            encoding="utf-8", errors="replace",
            timeout=1800,  # 30분 안전 상한 (CGV Selenium 여유)
        )
        out = proc.stdout
        err = proc.stderr
        code = proc.returncode
    except subprocess.TimeoutExpired:
        out = ""
        err = "TIMEOUT: 30분 초과"
        code = -1
    elapsed = (datetime.now(KST) - started).total_seconds()

    print(out)
    if err:
        print(err, file=sys.stderr)
    status = "OK" if code == 0 else "FAIL"
    print(f"\n[{label}] {status} · {elapsed:.1f}초")
    return {
        "label": label,
        "exit": code,
        "elapsedSec": round(elapsed, 1),
        "startedAt": started.isoformat(timespec="seconds"),
        # 로그 부피 제한 — 끝 3000자만 보관
        "stdoutTail": out[-3000:] if out else "",
        "stderrTail": err[-1500:] if err else "",
    }


def detect_new_stage_events():
    """promotions_*.json 의 stage 이벤트 중 screenings 누락 → 판독 대기 리스트."""
    pending = []
    for chain, fname in (
        ("CGV",   "promotions_cgv.json"),
        ("LOTTE", "promotions_lotte.json"),
        ("MEGA",  "promotions_megabox.json"),
        ("CINEQ", "promotions_cineq.json"),
    ):
        fpath = DATA_DIR / fname
        if not fpath.exists():
            continue
        try:
            doc = json.loads(fpath.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        for m in doc.get("movies", []):
            for e in m.get("events", []):
                if e.get("type") != "stage":
                    continue
                # 좌석 합산이 안 된 stage 이벤트 = SCREENINGS dict 미등록
                if not e.get("screenings") and not e.get("seats"):
                    pending.append({
                        "chain": chain,
                        "movieTitle": m["title"][:40],
                        "movieCd": m["movieCd"],
                        "eventId": str(e.get("eventId") or ""),
                        "eventName": e.get("name", ""),
                        "imagePath": e.get("imagePath") or
                                     (e.get("imagePaths") or [None])[0] or "",
                    })
    return pending


def chain_summary():
    """각 체인의 영화별 promoSeats 요약 (보고용)."""
    summary = {}
    for chain, fname in (
        ("CGV",   "promotions_cgv.json"),
        ("LOTTE", "promotions_lotte.json"),
        ("MEGA",  "promotions_megabox.json"),
        ("CINEQ", "promotions_cineq.json"),
    ):
        fpath = DATA_DIR / fname
        if not fpath.exists():
            continue
        try:
            doc = json.loads(fpath.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        movies = [
            {"title": m["title"][:30], "promoSeats": m.get("promoSeats", 0),
             "events": sum(m["counts"].values())}
            for m in doc.get("movies", [])
        ]
        summary[chain] = {
            "moviesMatched": len(movies),
            "totalEvents": sum(m["events"] for m in movies),
            "totalPromoSeats": sum(m["promoSeats"] for m in movies),
            "byMovie": sorted(movies, key=lambda x: x["promoSeats"], reverse=True),
        }
    return summary


def main():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now(KST).strftime("%Y-%m-%d")
    started = datetime.now(KST)

    print(f"\n{'#'*60}")
    print(f"# 시네마 프로모션 일일 동기화 · {today} {started.strftime('%H:%M:%S')}")
    print(f"{'#'*60}")

    results = [run_step(label, args) for label, args in STEPS]

    new_stage = detect_new_stage_events()
    summary = chain_summary()
    finished = datetime.now(KST)

    log = {
        "date": today,
        "startedAt": started.isoformat(timespec="seconds"),
        "finishedAt": finished.isoformat(timespec="seconds"),
        "totalSec": round((finished - started).total_seconds(), 1),
        "steps": results,
        "chainSummary": summary,
        "newStageEvents": new_stage,
    }
    log_path = LOG_DIR / f"{today}.json"
    log_path.write_text(json.dumps(log, ensure_ascii=False, indent=2),
                        encoding="utf-8")

    print(f"\n{'='*60}")
    print(f"✓ {today} 일일 동기화 완료 · {log['totalSec']:.0f}초")
    print(f"  로그: {log_path.relative_to(ROOT)}")
    failed = [r for r in results if r["exit"] != 0]
    if failed:
        print(f"  ⚠ 실패 단계 {len(failed)}건:")
        for r in failed:
            print(f"    [{r['label']}] exit={r['exit']}")
    if new_stage:
        print(f"\n  📋 LLM 판독 대기 stage 이벤트 {len(new_stage)}건:")
        for ev in new_stage[:15]:
            print(f"    [{ev['chain']:<6}] {ev['eventId']:>10}  "
                  f"{ev['eventName'][:55]}")
        if len(new_stage) > 15:
            print(f"    ... 외 {len(new_stage)-15}건 — 전체는 로그 파일 참조")
    else:
        print(f"\n  ✓ LLM 판독 대기 이벤트 없음 — 모든 stage 이벤트 좌석 합산 완료")

    # GitHub Pages 자동 배포 — .gitignore 로 이미지·로그 제외된 변경분만 push
    print(f"\n{'='*60}")
    print(f"[GIT-PUSH] 변경분 push 시도")
    try:
        subprocess.run(["git", "add", "-A"],
                       cwd=ROOT, check=False, capture_output=True)
        diff = subprocess.run(["git", "diff", "--cached", "--shortstat"],
                              cwd=ROOT, capture_output=True, text=True)
        if not (diff.stdout or "").strip():
            print(f"  변경분 없음 — push 스킵")
        else:
            print(f"  변경:{diff.stdout.strip()}")
            msg = f"Daily sync {today} ({log['totalSec']:.0f}s)"
            subprocess.run(["git", "commit", "-m", msg],
                           cwd=ROOT, check=False, capture_output=True)
            push = subprocess.run(["git", "push", "origin", "main"],
                                  cwd=ROOT, capture_output=True, text=True,
                                  timeout=120)
            if push.returncode == 0:
                print(f"  ✓ push 성공 → https://shyain456.github.io/Promo/")
            else:
                print(f"  ⚠ push 실패: {push.stderr[:300]}")
    except (subprocess.SubprocessError, OSError) as exc:
        print(f"  ⚠ git push 예외: {exc}")

    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
