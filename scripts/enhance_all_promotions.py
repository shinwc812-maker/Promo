#!/usr/bin/env python3
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "assets" / "data"

def load_json(fname):
    fpath = DATA_DIR / fname
    if not fpath.exists(): return None
    return json.loads(fpath.read_text(encoding="utf-8"))

def save_json(fname, data):
    fpath = DATA_DIR / fname
    fpath.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def main():
    # 1. 시트 DB 로드
    cgv_seats = {t["name"]: t for t in (load_json("theater_seats_cgv.json") or {}).get("theaters", [])}
    mega_seats = {t["name"]: t for t in (load_json("theater_seats_megabox.json") or {}).get("theaters", [])}
    cineq_seats = {t["name"]: t for t in (load_json("theater_seats_cineq.json") or {}).get("theaters", [])}

    # 2. CGV 고도화
    cgv_promos = load_json("promotions_cgv.json")
    if cgv_promos:
        for movie in cgv_promos.get("movies", []):
            for event in movie.get("events", []):
                if event["type"] == "stage":
                    # 기존 지점 목록이 있으면 사용, 없으면 보정
                    branches = event.get("branches", [])
                    if movie["title"] == "군체" and not branches:
                        branches = ["영등포", "용산아이파크몰"]
                    
                    details = []
                    total = 0
                    for bname in branches:
                        t = cgv_seats.get(bname)
                        if t:
                            s = sum(h["seats"] for h in t["halls"])
                            total += s
                            details.append({"name": bname, "seats": s})
                    event["branches"] = branches
                    event["totalSeats"] = total
                    event["branchDetails"] = details
        save_json("promotions_cgv.json", cgv_promos)

    # 3. 메가박스 고도화
    mega_promos = load_json("promotions_megabox.json")
    if mega_promos:
        for movie in mega_promos.get("movies", []):
            for event in movie.get("events", []):
                if event["type"] == "stage":
                    name = event["name"]
                    branches = []
                    if "와일드 씽" in name: branches = ["코엑스", "상암월드컵경기장", "목동"]
                    elif "군체" in name: branches = ["목동"]
                    elif "파이널 피스" in name: branches = ["코엑스", "홍대", "목동"]
                    
                    details = []
                    total = 0
                    for bname in branches:
                        t = mega_seats.get(bname)
                        if t:
                            s = sum(h["seats"] for h in t["halls"])
                            total += s
                            details.append({"name": bname, "seats": s})
                    event["branches"] = branches
                    event["totalSeats"] = total
                    event["branchDetails"] = details
        save_json("promotions_megabox.json", mega_promos)

    # 4. 씨네큐 고도화
    cineq_promos = load_json("promotions_cineq.json")
    if cineq_promos:
        for movie in cineq_promos.get("movies", []):
            for event in movie.get("events", []):
                if event["type"] == "stage":
                    name = event["name"]
                    branches = ["신도림"] # 씨네큐 무대인사는 거의 신도림
                    
                    details = []
                    total = 0
                    for bname in branches:
                        t = cineq_seats.get(bname)
                        if t:
                            s = sum(h["seats"] for h in t["halls"])
                            total += s
                            details.append({"name": bname, "seats": s})
                    event["branches"] = branches
                    event["totalSeats"] = total
                    event["branchDetails"] = details
        save_json("promotions_cineq.json", cineq_promos)

    print("✓ CGV, 메가박스, 씨네큐 프로모션-좌석 데이터 연동 완료")

if __name__ == "__main__":
    main()
