"""점포 주변 시설 조사 (카카오 로컬 API 카테고리 검색). AI 제안의 사실 재료입니다.

반경 500m와 1km 안의 시설 종류별 개수와, 가까운 학교 이름을 셉니다. 개수는 카카오가 알려 주는 검색 결과 수(total_count)입니다.
같은 위치는 하루에 한 번만 조사하고 결과를 기억해 둡니다. 인증키(KAKAO_REST_API_KEY)는 로그에 남기지 않습니다.
HTTP 호출 함수는 address.fetch_kakao 와 같은 모양(url, params, key)이라 시험에서 가짜로 바꿀 수 있습니다.
"""
import time
from concurrent.futures import ThreadPoolExecutor

from app.address import AddressError

CATEGORY_URL = "https://dapi.kakao.com/v2/local/search/category.json"
RADII = (500, 1000)
CATEGORIES = [
    ("SC4", "학교"), ("AC5", "학원"), ("PS3", "어린이집·유치원"), ("FD6", "음식점"), ("CE7", "카페"), ("CS2", "편의점"),
    ("SW8", "지하철역"), ("MT1", "대형마트"), ("BK9", "은행"), ("HP8", "병원"), ("PM9", "약국"), ("AD5", "숙박"),
]
SCHOOL_KINDS = ["초등학교", "중학교", "고등학교", "대학교"]
NEAR_SCHOOLS = 3
SEARCH_SIZE = 15  # 카카오가 한 번에 주는 최대 개수
TTL_SECONDS = 24 * 3600
_cache: dict = {}


def school_kind(name: str) -> str:
    for kind in SCHOOL_KINDS:
        if name.endswith(kind):
            return kind
    if "대학교" in name or name.endswith("대학"):  # "○○대학교 사범대학"처럼 대학교 안의 시설도 대학교로 봅니다
        return "대학교"
    return "기타 학교"


def school_key(name: str) -> str:
    """같은 학교로 셀 이름. 카카오는 대학 안의 단과대학·캠퍼스를 따로 알려 주기 때문에 "○○대학교"까지만 씁니다."""
    head, sep, _ = name.partition("대학교")
    return head + sep if sep else name


def distinct_schools(items: list[dict]) -> list[dict]:
    """가까운 순서로 온 학교 목록에서 같은 학교를 한 번만 남깁니다."""
    seen, out = set(), []
    for item in items:
        key = school_key(item["name"])
        if key not in seen:
            seen.add(key)
            out.append({**item, "name": key})
    return out


def _search(get, key: str, lat: float, lon: float, code: str, radius: int) -> dict:
    return get(CATEGORY_URL, {"category_group_code": code, "x": lon, "y": lat, "radius": radius, "size": SEARCH_SIZE, "sort": "distance"}, key)


def survey(get, key: str, lat: float, lon: float) -> dict:
    """{"counts": {500: {"학교": 3, ...}, 1000: {...}}, "schools": [{name, kind, distance_m}], "school_kinds": {500: {...}}}.
    카카오가 오류를 내면 AddressError."""
    cache_key = (round(lat, 3), round(lon, 3))
    hit = _cache.get(cache_key)
    if hit and time.monotonic() - hit[0] < TTL_SECONDS:
        return hit[1]
    jobs = [(code, name, radius) for radius in RADII for code, name in CATEGORIES]
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda j: _search(get, key, lat, lon, j[0], j[2]), jobs))
    counts: dict[int, dict[str, int]] = {r: {} for r in RADII}
    schools: dict[int, list[dict]] = {r: [] for r in RADII}
    for (code, name, radius), data in zip(jobs, results):
        total = int((data.get("meta") or {}).get("total_count") or 0)
        counts[radius][name] = total
        if code == "SC4":
            for doc in data.get("documents") or []:
                schools[radius].append({"name": str(doc.get("place_name", "")), "distance_m": int(float(doc.get("distance") or 0))})
    kinds = {r: {} for r in RADII}
    for radius, items in schools.items():
        unique = distinct_schools(items)
        for item in unique:
            kinds[radius][school_kind(item["name"])] = kinds[radius].get(school_kind(item["name"]), 0) + 1
        if counts[radius].get("학교", 0) <= SEARCH_SIZE:  # 목록이 전부 왔을 때만 중복을 뺀 학교 수로 바로잡습니다
            counts[radius]["학교"] = len(unique)
    near = [{"name": s["name"], "kind": school_kind(s["name"]), "distance_m": s["distance_m"]} for s in distinct_schools(schools[RADII[0]])[:NEAR_SCHOOLS]]
    result = {"counts": counts, "schools": near, "school_kinds": kinds}
    _cache[cache_key] = (time.monotonic(), result)
    return result


__all__ = ["survey", "AddressError", "CATEGORIES", "RADII", "school_kind"]
