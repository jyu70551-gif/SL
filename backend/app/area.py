"""점포 주변 상권·동네 조사. AI 제안의 사실 재료입니다. (docs/suggestions.md)

- 상가정보: 소상공인시장진흥공단 "상가(상권)정보"(공공데이터포털, STORE_API_KEY). 반경 500m 안 상가 업소의 업종과 편의점 수.
  이 자료에는 우리 점포를 따로 알아보는 표시가 없어서 편의점 수에는 우리 점포가 들어 있을 수 있습니다.
- 동네 인구: 통계청 SGIS(SGIS_ID 서비스 ID + SGIS_SECURITY_KEY 보안 Key). 점포가 있는 행정동의 인구·연령 분포. 동 단위라 반경으로 자를 수는 없습니다.
둘 다 하루(인구는 일주일) 동안 결과를 기억합니다. 키와 접근 토큰은 로그나 화면에 내보내지 않습니다.
HTTP 호출 함수(get)는 official.fetch_json 과 같은 모양(url, params)이라 시험에서 가짜 응답으로 바꿀 수 있습니다.
"""
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import date

from app.official import OfficialError

STORE_URL = "https://apis.data.go.kr/B553077/api/open/sdsc2/storeListInRadius"
STORE_RADIUS = 500
STORE_PAGE = 1000  # 한 번에 받을 수 있는 최대 개수
STORE_MAX_PAGES = 3  # 이보다 많은 지역은 일부만 세고 그렇다고 알립니다
CONVENIENCE = "편의점"
STORE_TTL = 24 * 3600

SGIS_BASE = "https://sgisapi.mods.go.kr/OpenAPI3"
SGIS_TTL = 7 * 24 * 3600
YEARS_BACK = 4  # 가장 최근 통계 연도를 이 햇수 안에서 찾습니다
# 연령 구분 코드(SGIS 정의서): 30 10대이하(0~9세), 31 10대, 32 20대 … 36 60대, 40 70대이상, 24 65세이상
AGE_BANDS = [("0~9세", "30"), ("10대", "31"), ("20대", "32"), ("30대", "33"), ("40대", "34"), ("50대", "35"), ("60대", "36"), ("70대 이상", "40")]
OLD_AGE_CODE = "24"

_store_cache: dict = {}
_area_cache: dict = {}
_token: dict = {"value": "", "expires_ms": 0}


# ---------------------------------------------------------------- 상가정보
def _store_page(get, key: str, lat: float, lon: float, page: int) -> dict:
    data = get(STORE_URL, {"serviceKey": key, "radius": STORE_RADIUS, "cx": lon, "cy": lat, "type": "json", "numOfRows": STORE_PAGE, "pageNo": page})
    header, body = (data or {}).get("header"), (data or {}).get("body")
    if not isinstance(header, dict) or not isinstance(body, dict):
        raise OfficialError("bad_response")
    if header.get("resultCode") != "00":
        raise OfficialError("api_error")
    items = body.get("items")
    return {"total": int(body.get("totalCount") or 0), "items": items if isinstance(items, list) else []}


def stores_survey(get, key: str, lat: float, lon: float) -> dict:
    """{"total", "partial", "groups": [(대분류, 곳 수)…많은 순], "convenience": 곳 수}. 받지 못하면 OfficialError."""
    cache_key = (round(lat, 3), round(lon, 3))
    hit = _store_cache.get(cache_key)
    if hit and time.monotonic() - hit[0] < STORE_TTL:
        return hit[1]
    first = _store_page(get, key, lat, lon, 1)
    items, total = list(first["items"]), first["total"]
    page = 1
    while len(items) < total and page < STORE_MAX_PAGES and items:
        page += 1
        items += _store_page(get, key, lat, lon, page)["items"]
    groups = Counter(str(i.get("indsLclsNm") or "기타") for i in items)
    result = {
        "total": total,
        "partial": len(items) < total,
        "groups": groups.most_common(),
        "convenience": sum(1 for i in items if i.get("indsSclsNm") == CONVENIENCE),
    }
    _store_cache[cache_key] = (time.monotonic(), result)
    return result


# ---------------------------------------------------------------- SGIS 동네 인구
def _auth(get, sid: str, secret: str) -> str:
    if _token["value"] and _token["expires_ms"] - time.time() * 1000 > 60_000:
        return _token["value"]
    data = get(SGIS_BASE + "/auth/authentication.json", {"consumer_key": sid, "consumer_secret": secret})
    result = (data or {}).get("result")
    if (data or {}).get("errCd") != 0 or not isinstance(result, dict) or not result.get("accessToken"):
        raise OfficialError("api_error")
    _token.update(value=result["accessToken"], expires_ms=int(result.get("accessTimeout") or 0))
    return _token["value"]


def _call(get, sid: str, secret: str, path: str, **params) -> dict:
    """SGIS 호출. 접근 토큰이 만료됐으면(-401) 한 번 새로 받아서 다시 부릅니다. 통계 자체의 오류(errCd)는 부른 쪽이 봅니다."""
    for _ in range(2):
        data = get(SGIS_BASE + path, {"accessToken": _auth(get, sid, secret), **params})
        if (data or {}).get("errCd") == -401:
            _token.update(value="", expires_ms=0)
            continue
        return data or {}
    raise OfficialError("api_error")


def _first(data: dict) -> dict | None:
    result = data.get("result")
    return result[0] if data.get("errCd") == 0 and isinstance(result, list) and result and isinstance(result[0], dict) else None


def _to_int(value) -> int | None:
    try:
        return int(float(str(value).replace(",", "")))
    except (TypeError, ValueError):
        return None


def _to_float(value) -> float | None:
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def area_survey(get, sid: str, secret: str, lat: float, lon: float, today: date) -> dict:
    """점포가 있는 행정동의 인구 정보. {"dong", "year", "population", "avg_age", "employees", "households", "avg_family", "bands": [(이름, 명)…], "old": 65세 이상 명}.
    값이 "N/A"인 항목은 None 입니다.
    받지 못하면 OfficialError."""
    cache_key = (round(lat, 3), round(lon, 3))
    hit = _area_cache.get(cache_key)
    if hit and time.monotonic() - hit[0] < SGIS_TTL:
        return hit[1]
    place = _first(_call(get, sid, secret, "/addr/rgeocodewgs84.json", x_coor=lon, y_coor=lat, addr_type=20))
    if not place or not all(place.get(k) for k in ("sido_cd", "sgg_cd", "emdong_cd")):
        raise OfficialError("bad_response")
    adm = f"{place['sido_cd']}{place['sgg_cd']}{place['emdong_cd']}"
    stats, year = None, None
    for y in range(today.year - 1, today.year - 1 - YEARS_BACK, -1):  # 가장 최근에 통계가 나온 연도를 찾습니다
        stats = _first(_call(get, sid, secret, "/stats/population.json", year=y, adm_cd=adm))
        if stats and _to_int(stats.get("tot_ppltn")):
            year = y
            break
    if not stats or year is None:
        raise OfficialError("api_error")

    def band(code: str) -> int | None:
        row = _first(_call(get, sid, secret, "/stats/searchpopulation.json", year=year, adm_cd=adm, gender=0, age_type=code))
        return _to_int(row.get("population")) if row else None

    codes = [code for _, code in AGE_BANDS] + [OLD_AGE_CODE]
    with ThreadPoolExecutor(max_workers=4) as pool:
        counts = list(pool.map(band, codes))
    if any(c is None for c in counts):
        raise OfficialError("api_error")
    result = {
        "dong": str(place.get("emdong_nm") or ""),
        "year": year,
        "population": _to_int(stats["tot_ppltn"]),
        "avg_age": _to_float(stats.get("avg_age")),
        "employees": _to_int(stats.get("employee_cnt")),  # 그 동네 사업체에서 일하는 사람(종사자) 수
        "households": _to_int(stats.get("tot_family")),
        "avg_family": _to_float(stats.get("avg_fmember_cnt")),
        "bands": [(name, n) for (name, _), n in zip(AGE_BANDS, counts[:-1])],
        "old": counts[-1],
    }
    _area_cache[cache_key] = (time.monotonic(), result)
    return result


__all__ = ["stores_survey", "area_survey", "OfficialError"]
