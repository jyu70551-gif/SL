"""날씨 가져오기 (docs/plan.md Phase 7, docs/forecast-considerations.md).

- 과거 날씨(학습용): 기상청 지상(종관, ASOS) 일자료. 점포에서 가장 가까운 관측소의 평균 기온과 일 강수량을 저장합니다.
- 내일 날씨(예측용): 기상청 단기예보. 저장하지 않고 필요할 때 받아서 씁니다.
- 둘 다 공공데이터포털 서비스이고 키는 따로입니다. 키는 로그나 화면에 내보내지 않습니다.
HTTP 호출 함수(get)는 official.fetch_json 과 같은 모양이라 시험에서 가짜 응답으로 바꿀 수 있습니다.
"""
import math
import re
import time
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import official
from app.auth import get_db, require_auth
from app.models import SalesUpload, WeatherDaily
from app.schools import _get, _key
from app.settings import _save, store_location

ASOS_URL = "http://apis.data.go.kr/1360000/AsosDalyInfoService/getWthrDataList"
FORECAST_URL = "http://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getVilageFcst"
RAIN_DAY_MM = 1.0  # 하루 강수량이 이 값 이상이면 "비 온 날"
ASOS_PAGE = 900

# 수도권 ASOS 관측소 (지점번호, 이름, 위도, 경도). 좌표는 근사값이고, 점포와 가장 가까운 곳을 고르는 데에만 씁니다.
STATIONS = [
    (108, "서울", 37.5714, 126.9658),
    (112, "인천", 37.4777, 126.6249),
    (119, "수원", 37.2723, 126.9853),
    (201, "강화", 37.7074, 126.4463),
    (202, "양평", 37.4886, 127.4946),
    (203, "이천", 37.2640, 127.4842),
    (98, "동두천", 37.9019, 127.0607),
    (99, "파주", 37.8859, 126.7665),
]


def nearest_station(lat: float, lon: float) -> tuple[tuple, float]:
    """점포에서 가장 가까운 관측소와 거리(km)"""
    best = min(STATIONS, key=lambda s: official.distance_m(lat, lon, s[2], s[3]))
    return best, official.distance_m(lat, lon, best[2], best[3]) / 1000


# ---------------------------------------------------------------- 과거 날씨 (ASOS 일자료)
def _items(data: dict) -> list[dict]:
    response = data.get("response") or {}
    code = (response.get("header") or {}).get("resultCode")
    if code == "03":  # 자료 없음
        return []
    if code != "00":
        raise official.OfficialError("api_error")
    items = ((response.get("body") or {}).get("items") or {})
    items = items.get("item") if isinstance(items, dict) else []
    return [items] if isinstance(items, dict) else list(items or [])


def fetch_observed(get, key: str, station_id: int, start: date, end: date) -> list[dict]:
    """[{day, station, temp, rain}] 평균 기온이 비어 있는 날은 건너뜁니다."""
    if not key:
        raise official.OfficialError("no_key")
    out, cursor = [], start
    while cursor <= end:
        chunk_end = min(end, cursor + timedelta(days=ASOS_PAGE - 1))
        data = get(ASOS_URL, {"serviceKey": key, "dataType": "JSON", "pageNo": 1, "numOfRows": 999, "dataCd": "ASOS", "dateCd": "DAY",
                              "startDt": cursor.strftime("%Y%m%d"), "endDt": chunk_end.strftime("%Y%m%d"), "stnIds": station_id})
        for item in _items(data):
            try:
                day, temp = date.fromisoformat(item["tm"]), float(item["avgTa"])
            except (KeyError, ValueError):
                continue
            out.append({"day": day, "station": str(item.get("stnNm", "")).strip(), "temp": temp, "rain": float(item.get("sumRn") or 0)})
        cursor = chunk_end + timedelta(days=1)
    return out


def missing_days(db: Session, until: date) -> list[date]:
    """매출 기록이 있는 날 중 아직 날씨를 저장하지 않은 날 (오늘 이전만)"""
    have = set(db.scalars(select(WeatherDaily.day)))
    return sorted({d for d in db.scalars(select(SalesUpload.sales_date)) if d <= until and d not in have})


def sync_observed(db: Session, get, key: str, lat: float, lon: float, today: date | None = None) -> dict:
    """빠진 날의 관측 날씨를 받아 저장합니다. 이미 저장된 날은 건드리지 않습니다."""
    today = today or date.today()
    station, km = nearest_station(lat, lon)
    todo = missing_days(db, today - timedelta(days=1))
    added = 0
    if todo:
        wanted = set(todo)
        for row in fetch_observed(get, key, station[0], todo[0], todo[-1]):
            if row["day"] in wanted:
                db.add(WeatherDaily(day=row["day"], station=row["station"] or station[1], avg_temp=row["temp"], rain_mm=row["rain"]))
                added += 1
        _save(db)
    return {"added": added, "asked": len(todo), "station": station[1], "distance_km": round(km, 1)}


def observed_map(db: Session) -> dict[date, tuple[float, float]]:
    return {w.day: (w.avg_temp, w.rain_mm) for w in db.scalars(select(WeatherDaily))}


# ---------------------------------------------------------------- 내일 예보 (단기예보)
def to_grid(lat: float, lon: float) -> tuple[int, int]:
    """위도·경도를 기상청 동네예보 격자 번호(nx, ny)로 바꿉니다 (기상청 공개 변환식)."""
    re_, grid, slat1, slat2, olon, olat, xo, yo = 6371.00877 / 5.0, 5.0, 30.0, 60.0, 126.0, 38.0, 43, 136
    rad = math.pi / 180.0
    sn = math.log(math.cos(slat1 * rad) / math.cos(slat2 * rad)) / math.log(
        math.tan(math.pi * 0.25 + slat2 * rad * 0.5) / math.tan(math.pi * 0.25 + slat1 * rad * 0.5))
    sf = math.tan(math.pi * 0.25 + slat1 * rad * 0.5) ** sn * math.cos(slat1 * rad) / sn
    ro = re_ * sf / math.tan(math.pi * 0.25 + olat * rad * 0.5) ** sn
    ra = re_ * sf / math.tan(math.pi * 0.25 + lat * rad * 0.5) ** sn
    theta = lon * rad - olon * rad
    theta = (theta + math.pi) % (2 * math.pi) - math.pi
    theta *= sn
    return int(math.floor(ra * math.sin(theta) + xo + 0.5)), int(math.floor(ro - ra * math.cos(theta) + yo + 0.5))


def parse_rain(text: str) -> float:
    """예보의 강수량 글("강수없음", "1mm 미만", "30.0~50.0mm", "50.0mm 이상", "2.5mm")을 mm 숫자로 바꿉니다."""
    text = (text or "").strip()
    if not text or "없음" in text:
        return 0.0
    numbers = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", text)]
    if not numbers:
        return 0.0
    if "미만" in text:
        return numbers[0] / 2
    return sum(numbers[:2]) / len(numbers[:2]) if "~" in text else numbers[0]


def _base_time(now: datetime) -> tuple[date, str]:
    """가장 최근에 발표된 예보 시각 (02·05·08·11·14·17·20·23시 발표, 발표 15분 뒤부터 받을 수 있음)"""
    shifted = now - timedelta(minutes=15)
    hours = [h for h in (2, 5, 8, 11, 14, 17, 20, 23) if h <= shifted.hour]
    if hours:
        return shifted.date(), f"{hours[-1]:02d}00"
    return shifted.date() - timedelta(days=1), "2300"


def forecast_days(get, key: str, lat: float, lon: float, targets: list[date], now: datetime | None = None) -> dict[date, dict]:
    """여러 날의 예보를 한 번에 받습니다. {날짜: {temp(시간별 평균 ℃), min_temp, max_temp, rain_mm, pop(강수확률 최대 %)}}.
    예보 범위 밖인 날은 결과에 없습니다."""
    if not key:
        raise official.OfficialError("no_key")
    base_day, base_time = _base_time(now or datetime.now())
    nx, ny = to_grid(lat, lon)
    data = get(FORECAST_URL, {"serviceKey": key, "dataType": "JSON", "pageNo": 1, "numOfRows": 1000, "base_date": base_day.strftime("%Y%m%d"),
                              "base_time": base_time, "nx": nx, "ny": ny})
    wanted = {t.strftime("%Y%m%d"): t for t in targets}
    temps: dict[str, list[float]] = {k: [] for k in wanted}
    rain = {k: 0.0 for k in wanted}
    pops: dict[str, list[float]] = {k: [] for k in wanted}
    for item in _items(data):
        day = item.get("fcstDate")
        if day not in wanted:
            continue
        category, value = item.get("category"), str(item.get("fcstValue", ""))
        try:
            if category == "TMP":
                temps[day].append(float(value))
            elif category == "PCP":
                rain[day] += parse_rain(value)
            elif category == "POP":
                pops[day].append(float(value))
        except ValueError:
            continue
    out = {}
    for key_, target in wanted.items():
        if temps[key_]:
            t = temps[key_]
            out[target] = {"temp": sum(t) / len(t), "min_temp": min(t), "max_temp": max(t), "rain_mm": rain[key_], "pop": max(pops[key_]) if pops[key_] else None}
    return out


def fetch_forecast(get, key: str, lat: float, lon: float, target: date, now: datetime | None = None) -> dict | None:
    """target 날짜의 예보. 예보 범위 밖이면 None."""
    return forecast_days(get, key, lat, lon, [target], now).get(target)


# ---------------------------------------------------------------- 설정 화면용 주소
router = APIRouter(prefix="/api/settings/weather", tags=["weather"], dependencies=[Depends(require_auth)])


def _status(db: Session) -> dict:
    count = db.scalar(select(func.count()).select_from(WeatherDaily)) or 0
    last = db.scalar(select(func.max(WeatherDaily.day)))
    first = db.scalar(select(func.min(WeatherDaily.day)))
    stations = sorted(set(db.scalars(select(WeatherDaily.station))))
    return {"days": count, "first_day": first.isoformat() if first else None, "last_day": last.isoformat() if last else None, "stations": stations,
            "missing": len(missing_days(db, date.today() - timedelta(days=1)))}


@router.get("")
def read_weather(db: Session = Depends(get_db)):
    location = store_location(db)
    base = _status(db)
    if location is None:
        return {**base, "status": "no_location", "station": None}
    station, km = nearest_station(*location)
    return {**base, "status": "ready" if _key("WEATHER_PAST_API_KEY") else "no_key", "station": {"name": station[1], "distance_km": round(km, 1)}}


@router.post("/sync")
def sync_weather(request: Request, db: Session = Depends(get_db)):
    location = store_location(db)
    if location is None:
        return {"status": "no_location"}
    key = _key("WEATHER_PAST_API_KEY")
    if not key:
        return {"status": "no_key"}
    try:
        result = sync_observed(db, _get(request), key, *location)
    except official.OfficialError as error:
        raise HTTPException(status_code=502, detail={"code": "source_unavailable", "reason": error.code}) from None
    return {"status": "ready", **result, **_status(db)}
