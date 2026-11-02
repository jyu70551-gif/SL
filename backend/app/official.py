"""공식 데이터에서 근처 학교와 학교 방학 일정을 가져옵니다 (docs/plan.md 6-2).

- 학교 위치: 공공데이터포털 전국초중등학교위치표준데이터 (위도·경도)
- 학교 코드·학사일정: NEIS 교육정보 개방 포털
- 근처 학교는 거리 계산(코드)으로 고르고, 방학 기간은 학사일정의 행사명 규칙으로 추정합니다.
  AI는 쓰지 않습니다. 추정은 점주가 확인한 뒤에만 저장됩니다.
이 모듈의 함수는 HTTP 호출 함수(get)를 받아서 시험에서 가짜 응답으로 바꿀 수 있습니다. 인증키는 로그에 남기지 않습니다.
"""
import json
import math
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta

SCHOOL_PLACE_URL = "https://api.data.go.kr/openapi/tn_pubr_public_elesch_mskul_lc_api"
NEIS_SCHOOL_INFO_URL = "https://open.neis.go.kr/hub/schoolInfo"
NEIS_SCHEDULE_URL = "https://open.neis.go.kr/hub/SchoolSchedule"
HOLIDAY_URL = "http://apis.data.go.kr/B090041/openapi/service/SpcdeInfoService/getRestDeInfo"
MARKET_URL = "https://api.data.go.kr/openapi/tn_pubr_public_trdit_mrkt_api"
RADIUS_M = 500
PAGE_SIZE = 1000
MAX_PAGES = 30  # 한 번에 받는 상한(약 12,000곳 = 12쪽). 응답이 이상할 때 끝없이 돌지 않도록
TIMEOUT_SECONDS = 25

# 교육청 이름에 들어 있는 말 → NEIS 시·도교육청 코드
ATPT_CODES = [
    ("서울", "B10"), ("부산", "C10"), ("대구", "D10"), ("인천", "E10"), ("광주", "F10"), ("대전", "G10"), ("울산", "H10"),
    ("세종", "I10"), ("경기", "J10"), ("강원", "K10"), ("충청북", "M10"), ("충북", "M10"), ("충청남", "N10"), ("충남", "N10"),
    ("전라북", "P10"), ("전북", "P10"), ("전라남", "Q10"), ("전남", "Q10"), ("경상북", "R10"), ("경북", "R10"),
    ("경상남", "S10"), ("경남", "S10"), ("제주", "T10"),
]


class OfficialError(Exception):
    """공식 데이터를 받지 못했을 때. code 는 화면 안내용입니다: network / bad_response / api_error / no_key"""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def fetch_json(url: str, params: dict) -> dict:
    """GET 으로 JSON 을 받습니다. 오류 메시지에 주소(= 인증키)가 담기지 않도록 내용만 OfficialError 로 바꿉니다."""
    request = urllib.request.Request(url + "?" + urllib.parse.urlencode(params), headers={"User-Agent": "SL/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError):
        raise OfficialError("network") from None
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise OfficialError("bad_response") from None


def atpt_code_of(education_office_name: str) -> str | None:
    """교육청 이름에서 NEIS 시·도교육청 코드. 알 수 없으면 None.
    "전남광주통합특별시교육청"처럼 두 지역이 합쳐진 이름은 광주(F10)와 전남(Q10)을 구분할 수 없어서 None 입니다.
    (이름에 "광주"가 들어 있다고 F10으로 읽으면 전남 학교 전체를 못 찾습니다)"""
    if "통합" in education_office_name:
        return None
    for word, code in ATPT_CODES:
        if word in education_office_name:
            return code
    return None


def atpt_codes_of(education_office_name: str) -> list[str]:
    """학교를 찾아볼 NEIS 교육청 코드 후보. 합쳐진 교육청은 전남(Q10)과 광주(F10) 둘 다, 모르면 빈 목록."""
    if "통합" in education_office_name:
        return ["Q10", "F10"]
    code = atpt_code_of(education_office_name)
    return [code] if code else []


def distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """두 지점 사이 거리(미터, 구면 근사)"""
    radius = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


# ---------------------------------------------------------------- 학교 위치
def load_school_places(get, key: str) -> list[dict]:
    """전국 초·중·고 학교 위치를 전부 받습니다. [{school_id, name, kind, lat, lon, address, edu_office, status}]"""
    if not key:
        raise OfficialError("no_key")
    places: list[dict] = []
    total = None
    for page in range(1, MAX_PAGES + 1):
        data = get(SCHOOL_PLACE_URL, {"serviceKey": key, "pageNo": page, "numOfRows": PAGE_SIZE, "type": "json"})
        header = data.get("header") or {}
        if header.get("resultCode") not in ("00", "0"):
            raise OfficialError("api_error")
        body = data.get("body") or {}
        items = (body.get("items") or {}).get("item") or []
        if isinstance(items, dict):
            items = [items]
        total = int(body.get("totalCount") or 0) if total is None else total
        for item in items:
            try:
                lat, lon = float(item["latitude"]), float(item["longitude"])
            except (KeyError, TypeError, ValueError):
                continue  # 좌표가 없는 학교는 거리를 잴 수 없습니다
            if not (33 <= lat <= 39 and 124 <= lon <= 132):
                continue
            places.append(
                {
                    "school_id": str(item.get("schoolId", "")),
                    "name": str(item.get("schoolNm", "")).strip(),
                    "kind": str(item.get("schoolSe", "")).strip(),
                    "lat": lat,
                    "lon": lon,
                    "address": str(item.get("rdnmadr") or item.get("lnmadr") or "").strip(),
                    "edu_office": str(item.get("cddcNm", "")).strip(),
                    "status": str(item.get("operSttus", "")).strip(),
                }
            )
        if not items or page * PAGE_SIZE >= (total or 0):
            break
    return places


def nearby(places, lat: float, lon: float, radius_m: float = RADIUS_M) -> list[dict]:
    """반경 안의 운영 중인 학교를 가까운 순서로. places 는 dict 또는 같은 이름의 속성을 가진 객체."""
    out = []
    for p in places:
        get_ = p.get if isinstance(p, dict) else (lambda k, _p=p: getattr(_p, k))
        if get_("status") not in ("", "운영"):
            continue
        d = distance_m(lat, lon, get_("lat"), get_("lon"))
        if d <= radius_m:
            out.append({"school_id": get_("school_id"), "name": get_("name"), "kind": get_("kind"), "address": get_("address"), "distance_m": round(d)})
    return sorted(out, key=lambda s: (s["distance_m"], s["name"]))


# ---------------------------------------------------------------- 공휴일 (한국천문연구원 특일 정보)
def fetch_holidays(get, key: str, year: int) -> list[dict]:
    """그 해의 공휴일(대체공휴일 포함) [{date, name}]. 쉬는 날(isHoliday=Y)만 담습니다."""
    if not key:
        raise OfficialError("no_key")
    data = get(HOLIDAY_URL, {"serviceKey": key, "solYear": year, "numOfRows": 100, "_type": "json"})
    response = data.get("response") or {}
    if (response.get("header") or {}).get("resultCode") != "00":
        raise OfficialError("api_error")
    items = ((response.get("body") or {}).get("items") or {})
    items = items.get("item") if isinstance(items, dict) else []  # 결과가 없으면 items 가 빈 글자로 옵니다
    if isinstance(items, dict):
        items = [items]
    out = []
    for item in items or []:
        try:
            day = date(int(str(item["locdate"])[:4]), int(str(item["locdate"])[4:6]), int(str(item["locdate"])[6:8]))
        except (KeyError, ValueError):
            continue
        if item.get("isHoliday") == "Y" and day.year == year:
            out.append({"date": day, "name": str(item.get("dateName", "")).strip()[:40] or "공휴일"})
    return sorted(out, key=lambda h: h["date"])


# ---------------------------------------------------------------- 전통시장 (장날)
def market_days_from_cycle(cycle: str) -> list[int] | None:
    """개설 주기 글("3일+8일")에서 매월 장이 서는 날짜. 5일장(n일+n+5일)이 아니면 None.
    예: "3일+8일" → 3·8·13·18·23·28일, "5일+10일" → 5·10·15·20·25·30일"""
    numbers = sorted(int(n) for n in re.findall(r"\d+", cycle))
    if len(numbers) != 2 or numbers[1] - numbers[0] != 5 or not 1 <= numbers[0] <= 5:
        return None
    return [d for d in range(1, 32) if d % 5 == numbers[0] % 5]


def load_market_places(get, key: str) -> list[dict]:
    """전국 전통시장 위치와 개설 주기. kind: permanent(상설·매일) / periodic(5일장) / unknown(읽을 수 없는 주기)"""
    if not key:
        raise OfficialError("no_key")
    places: list[dict] = []
    total = None
    for page in range(1, MAX_PAGES + 1):
        data = get(MARKET_URL, {"serviceKey": key, "pageNo": page, "numOfRows": PAGE_SIZE, "type": "json"})
        if (data.get("header") or {}).get("resultCode") not in ("00", "0"):
            raise OfficialError("api_error")
        body = data.get("body") or {}
        items = (body.get("items") or {}).get("item") or []
        if isinstance(items, dict):
            items = [items]
        total = int(body.get("totalCount") or 0) if total is None else total
        for item in items:
            try:
                lat, lon = float(item["latitude"]), float(item["longitude"])
            except (KeyError, TypeError, ValueError):
                continue
            if not (33 <= lat <= 39 and 124 <= lon <= 132):
                continue
            name = str(item.get("mrktNm", "")).strip()
            address = str(item.get("rdnmadr") or item.get("lnmadr") or "").strip()
            cycle = str(item.get("mrktEstblCycle", "")).strip()
            days = market_days_from_cycle(cycle)
            kind = "periodic" if days else "permanent" if cycle in ("매일", "상설") else "unknown"
            if not name:
                continue
            places.append({"market_id": f"{name}|{address}", "name": name, "address": address, "lat": lat, "lon": lon,
                           "cycle": cycle, "kind": kind, "days": days or []})
        if not items or page * PAGE_SIZE >= (total or 0):
            break
    return places


def nearby_markets(places, lat: float, lon: float, radius_m: float = RADIUS_M) -> list[dict]:
    out = []
    for p in places:
        d = distance_m(lat, lon, p["lat"], p["lon"])
        if d <= radius_m:
            out.append({k: p[k] for k in ("market_id", "name", "address", "cycle", "kind", "days")} | {"distance_m": round(d)})
    return sorted(out, key=lambda m: (m["distance_m"], m["name"]))


# ---------------------------------------------------------------- NEIS
def _neis_rows(data: dict, service: str) -> list[dict]:
    """NEIS 응답에서 행 목록. 결과가 없으면 빈 목록, 오류 코드면 OfficialError."""
    if service not in data:
        result = (data.get("RESULT") or {}).get("CODE", "")
        if result == "INFO-200":  # 해당하는 데이터가 없습니다
            return []
        raise OfficialError("api_error")
    parts = data[service]
    head = (parts[0].get("head") or []) if parts else []
    code = next((h["RESULT"]["CODE"] for h in head if "RESULT" in h), "")
    if code == "INFO-200":
        return []
    if code and code != "INFO-000":
        raise OfficialError("api_error")
    return parts[1].get("row", []) if len(parts) > 1 else []


_PAREN = re.compile(r"\([^)]*\)")
_ROAD = re.compile(r"([가-힣0-9]+(?:로|길)(?:\d+번?길)?)\s*(\d+(?:-\d+)?)(?:번지)?\s*$")


def road_key(address: str) -> tuple[str, str] | None:
    """도로명주소 끝의 (도로 이름, 건물 번호). 시·구·도 이름이 자료마다 달라도(화성시 만세구 ↔ 화성시, 강원특별자치도 ↔ 강원도,
    "84" ↔ "84번지") 같은 건물을 알아보기 위한 것입니다. 번호가 없으면 None."""
    m = _ROAD.search(_PAREN.sub("", str(address)).strip())
    return (m.group(1), m.group(2)) if m else None


def neis_school_code(get, key: str, atpt, name: str, address: str) -> tuple[str, str] | None:
    """학교 위치 자료의 학교를 NEIS의 (교육청 코드, 학교 코드)로 연결합니다. 못 찾으면 None.
    atpt 는 교육청 코드 후보(글자 하나, 목록, 또는 모르면 None).
    1) 후보 교육청 안에서 찾습니다. 도로명주소가 같으면 그 학교, 아니면 도로명+건물 번호가 같은 학교, 아니면 같은 이름이 하나뿐일 때 그것.
    2) 못 찾으면 교육청을 지정하지 않고 전국에서 찾습니다. 이때는 이름만 같은 다른 지역 학교와 섞이지 않게
       **도로명주소(또는 도로명+건물 번호)가 같은 학교만** 인정합니다. (교육청 이름이 합쳐졌거나 바뀐 경우에도 찾기 위해서입니다)"""
    if not key:
        raise OfficialError("no_key")
    codes = [atpt] if isinstance(atpt, str) else list(atpt or [])
    norm = lambda s: "".join(str(s).split())
    wanted_road = road_key(address)

    def search(code: str | None) -> list[dict]:
        params = {"KEY": key, "Type": "json", "pIndex": 1, "pSize": 100, "SCHUL_NM": name}
        if code:
            params["ATPT_OFCDC_SC_CODE"] = code
        return _neis_rows(get(NEIS_SCHOOL_INFO_URL, params), "schoolInfo")

    def pick(rows: list[dict], allow_single: bool) -> tuple[str, str] | None:
        same = [r for r in rows if norm(r.get("ORG_RDNMA", "")) == norm(address)]
        if not same and wanted_road:
            same = [r for r in rows if road_key(r.get("ORG_RDNMA", "")) == wanted_road]
            same = same if len(same) == 1 else []  # 같은 건물이 둘이면 구분할 수 없으니 고르지 않습니다
        if same:
            return same[0]["ATPT_OFCDC_SC_CODE"], same[0]["SD_SCHUL_CODE"]
        if allow_single and len(rows) == 1:
            return rows[0]["ATPT_OFCDC_SC_CODE"], rows[0]["SD_SCHUL_CODE"]
        return None

    for code in codes:
        found = pick(search(code), allow_single=True)
        if found:
            return found
    return pick(search(None), allow_single=False)


def fetch_schedule(get, key: str, atpt: str, school_code: str, start: date, end: date) -> list[dict]:
    if not key:
        raise OfficialError("no_key")
    rows: list[dict] = []
    for page in range(1, 6):
        data = get(
            NEIS_SCHEDULE_URL,
            {"KEY": key, "Type": "json", "pIndex": page, "pSize": 1000, "ATPT_OFCDC_SC_CODE": atpt, "SD_SCHUL_CODE": school_code,
             "AA_FROM_YMD": start.strftime("%Y%m%d"), "AA_TO_YMD": end.strftime("%Y%m%d")},
        )
        batch = _neis_rows(data, "SchoolSchedule")
        rows.extend(batch)
        if len(batch) < 1000:
            break
    return rows


# ---------------------------------------------------------------- 방학 기간 추정
def _ymd(text: str) -> date | None:
    try:
        return date(int(text[:4]), int(text[4:6]), int(text[6:8]))
    except (ValueError, TypeError):
        return None


def _season_label(name: str, day: date) -> str:
    if "여름" in name:
        return "여름방학"
    if "겨울" in name:
        return "겨울방학"
    if "봄" in name:
        return "봄방학"
    return "여름방학" if 6 <= day.month <= 9 else "겨울방학" if day.month in (11, 12, 1, 2) else "방학"


def _gap_is_only_weekend(a: date, b: date) -> bool:
    """a 와 b 사이의 날이 모두 토·일이면 이어진 기간으로 봅니다. (평일만 적어 두는 학교가 있어서)"""
    day = a + timedelta(days=1)
    while day < b:
        if day.weekday() < 5:
            return False
        day += timedelta(days=1)
    return True


def vacation_periods(rows: list[dict]) -> list[dict]:
    """학사일정 행에서 방학 기간을 찾습니다. [{label, start_date, end_date, days}] (시작일 순서)

    1순위: 날마다 '여름방학'처럼 적혀 있는 행(방학식·개학식 같은 '식'은 제외)을 이어서 한 기간으로 묶습니다.
    2순위: 그런 행이 없으면 '방학식' 다음 날부터 그다음 '개학식' 전날까지를 방학으로 봅니다.
    학교가 적은 행사명 그대로를 쓰며, 이름을 알아볼 수 없으면 건너뜁니다. (점주가 직접 입력할 수 있습니다)
    """
    daily: dict[date, str] = {}
    start_days: list[date] = []
    resume_days: list[tuple[date, str]] = []
    for row in rows:
        name, day = str(row.get("EVENT_NM", "")).strip(), _ymd(str(row.get("AA_YMD", "")))
        if day is None:
            continue
        if "방학식" in name:
            start_days.append((day, name))
        elif "방학" in name:
            daily[day] = _season_label(name, day)
        if "개학" in name:
            resume_days.append(day)

    periods: list[dict] = []
    current: dict | None = None
    for day in sorted(daily):
        label = daily[day]
        joined = current is not None and label == current["label"] and ((day - current["end"]).days <= 1 or _gap_is_only_weekend(current["end"], day))
        if joined:
            current["end"] = day
        else:
            if current:
                periods.append(current)
            current = {"label": label, "start": day, "end": day}
    if current:
        periods.append(current)

    if not periods:  # 방학식·개학식만 적어 둔 학교
        for start_day, name in sorted(start_days):
            after = sorted(d for d in resume_days if d > start_day)
            if after and (after[0] - start_day).days >= 2:
                periods.append({"label": _season_label(name, start_day), "start": start_day + timedelta(days=1), "end": after[0] - timedelta(days=1)})

    return [
        {"label": p["label"], "start_date": p["start"].isoformat(), "end_date": p["end"].isoformat(), "days": (p["end"] - p["start"]).days + 1}
        for p in periods
    ]
