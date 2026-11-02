r"""전국 학교가 NEIS 학교 코드로 연결되는지 점검하는 도구 (앱의 official.neis_school_code 를 그대로 씁니다).

학교 위치 자료(공공데이터포털)의 모든 학교를 NEIS 전체 학교 목록과 맞춰 보고, 못 찾는 학교를 원인별로 보여 줍니다.
NEIS 전체 목록은 한 번 받아 backend/lab/neis_all.json 에 저장해 두고 다시 씁니다. (--refresh 면 새로 받음, 호출 약 20번)
교육청 이름이 바뀌거나 합쳐지는 일이 또 생겼을 때, 학교 연결 규칙을 고친 뒤에 돌려서 확인합니다.

    cd backend
    .\.venv\Scripts\python.exe tools\audit_schools.py            # 점검
    .\.venv\Scripts\python.exe tools\audit_schools.py --refresh  # NEIS 목록을 새로 받고 점검
"""
import argparse
import collections
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from app import config, official  # noqa: E402

CACHE = BACKEND / "lab" / "neis_all.json"
ATPT_CODES = ["B10", "C10", "D10", "E10", "F10", "G10", "H10", "I10", "J10", "K10", "M10", "N10", "P10", "Q10", "R10", "S10", "T10"]


def download_neis(key: str) -> list[dict]:
    rows: list[dict] = []
    for code in ATPT_CODES:
        page = 1
        while True:
            data = official.fetch_json(official.NEIS_SCHOOL_INFO_URL, {"KEY": key, "Type": "json", "pIndex": page, "pSize": 1000, "ATPT_OFCDC_SC_CODE": code})
            batch = official._neis_rows(data, "schoolInfo")
            rows += batch
            if len(batch) < 1000:
                break
            page += 1
    return rows


def offline_get(neis: list[dict]):
    """NEIS 학교 목록에서 찾아 주는 가짜 호출. 앱 함수가 보내는 이름·교육청 조건을 그대로 흉내 냅니다."""
    def get(url, params):
        rows = [r for r in neis if r["SCHUL_NM"] == params.get("SCHUL_NM") and (not params.get("ATPT_OFCDC_SC_CODE") or r["ATPT_OFCDC_SC_CODE"] == params["ATPT_OFCDC_SC_CODE"])]
        if not rows:
            return {"RESULT": {"CODE": "INFO-200", "MESSAGE": "해당하는 데이터가 없습니다."}}
        return {"schoolInfo": [{"head": [{"list_total_count": len(rows)}, {"RESULT": {"CODE": "INFO-000"}}]}, {"row": rows[:100]}]}
    return get


def main() -> int:
    parser = argparse.ArgumentParser(description="전국 학교의 NEIS 연결 점검")
    parser.add_argument("--refresh", action="store_true", help="NEIS 전체 학교 목록을 새로 받습니다")
    parser.add_argument("--max-fail", type=int, default=None, help="못 찾는 학교가 이 수를 넘으면 종료 코드 1")
    args = parser.parse_args()
    data_key, neis_key = config.read_env_key("DATA_GO_KR_API_KEY", config.AI_ENV_FILE), config.read_env_key("NEIS_API_KEY", config.AI_ENV_FILE)
    if not data_key or not neis_key:
        raise SystemExit("backend/.env 에 DATA_GO_KR_API_KEY 와 NEIS_API_KEY 가 있어야 해요.")
    places = official.load_school_places(official.fetch_json, data_key)
    if args.refresh or not CACHE.exists():
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(download_neis(neis_key), ensure_ascii=False), encoding="utf-8")
    neis = json.loads(CACHE.read_text(encoding="utf-8"))
    get = offline_get(neis)
    by_name = collections.defaultdict(list)
    for r in neis:
        by_name[r["SCHUL_NM"]].append(r)

    found = 0
    fails: list[dict] = []
    wrong_office = collections.Counter()
    for p in places:
        atpts = official.atpt_codes_of(p["edu_office"])
        hit = official.neis_school_code(get, "offline", atpts, p["name"], p["address"])
        if hit is None:
            fails.append(p)
            continue
        found += 1
        if len(atpts) == 1 and hit[0] != atpts[0]:  # 교육청 이름으로 정한 코드가 NEIS의 실제 코드와 다른 경우
            wrong_office[(p["edu_office"], atpts[0], hit[0])] += 1
    print(f"학교 {len(places)}곳 중 연결 {found}곳 ({found / len(places) * 100:.2f}%), 못 찾음 {len(fails)}곳")
    for (office, ours, real), n in wrong_office.most_common():
        print(f"  ⚠ 교육청 코드 불일치: {office} → 우리 {ours}, 실제 {real} ({n}곳)")
    causes = collections.Counter()
    for p in fails:
        causes["NEIS에 같은 이름이 없음 (외국인학교, 방송통신고 등)" if not by_name.get(p["name"]) else "이름은 같지만 주소로 구분할 수 없음"] += 1
    for cause, n in causes.most_common():
        print(f"  - {cause}: {n}곳")
    for p in fails:
        print(f"    {p['name']} | {p['edu_office']} | {p['address']}")
    return 1 if args.max_fail is not None and len(fails) > args.max_fail else 0


if __name__ == "__main__":
    sys.exit(main())
