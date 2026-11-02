"""내일 예상 매출 (docs/plan.md Phase 7, docs/forecast-considerations.md, docs/stats-guide.md 4장).

총매출을 로그로 바꾼 뒤 요일·장날·공휴일·방학·기온·비 온 날을 넣은 규제 회귀(릿지)로 예상합니다.
- 자료가 적을 때 계수가 우연한 값으로 커지지 않도록 계수에 벌금을 매깁니다. 벌금의 세기는 과거 자료로 직접 고릅니다(빼고 맞혀 보기).
- 과거 날들을 하루씩 그날 이전 자료만으로 예측해 보고(걸러서 맞히기), 평소 기준(같은 요일 중간값, 최근 중간값)보다 꾸준히 낫지 않으면
  모형을 쓰지 않고 평소 기준으로 보여 줍니다. 범위는 그 방법의 과거 오차로 만듭니다.
- 기상특보는 쓰지 않습니다. 선형대수는 직접 풉니다(작은 연립방정식이라 외부 라이브러리가 필요 없습니다).
"""
import hashlib
import math
import statistics
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import day_context, official, weather
from app.auth import get_db, require_auth
from app.models import DailySale, SalesUpload
from app.schools import _get, _key
from app.settings import store_location

router = APIRouter(prefix="/api/forecast", tags=["forecast"], dependencies=[Depends(require_auth)])

WEEKDAYS = "월화수목금토일"
MIN_DAYS = 12  # 이보다 적으면 예상하지 않습니다
MIN_TRAIN = 28  # 걸러서 맞힐 때 처음 학습에 쓰는 최소 일수 (자료가 40일 미만이면 8일)
SHORT_MIN_TRAIN = 8
BACKTEST_DAYS = 45  # 걸러서 맞혀 보는 최근 날 수
MIN_TEST = 15  # 모형을 쓸지 판단하려면 맞혀 본 날이 이만큼은 있어야 합니다
MIN_RANGE_TEST = 8  # 범위를 말하려면 맞혀 본 날이 이만큼은 있어야 합니다
BEAT_MARGIN = 0.95  # 모형의 평균 오차가 평소 기준의 95% 이하일 때만 씁니다
LAMBDAS = (0.5, 2.0, 5.0, 10.0, 20.0, 50.0, 100.0)
LAMBDA_EVERY = 10  # 벌금 세기를 다시 고르는 간격(맞혀 보는 날 수)
WEEKDAY_BASE_DAYS = 8  # 같은 요일 중간값에 쓰는 최근 같은 요일 수
RECENT_DAYS = 56  # 최근 중간값에 쓰는 일수
LEVEL_DAYS = 14  # 최근 오차 보정: 최근 이만큼의 날에서 모형이 평균적으로 얼마나 빗나갔는지 보고
LEVEL_SHARE = 0.5  # 그 오차의 이 비율만큼 예상을 옮깁니다 (매출 수준이 서서히 달라지는 것을 따라가기 위해. 시연 자료 하나로 고른 값)
FORECAST_WIDEN = 1.1  # 예보 날씨를 쓸 때는 날씨가 틀릴 수 있어 범위를 조금 넓힙니다


def _today() -> date:
    return date.today()


def _now() -> datetime:
    return datetime.now()


# ---------------------------------------------------------------- 작은 선형대수
def _invert(a: list[list[float]]) -> list[list[float]]:
    n = len(a)
    m = [row[:] + [1.0 if i == j else 0.0 for j in range(n)] for i, row in enumerate(a)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(m[r][c]))
        if abs(m[p][c]) < 1e-12:
            raise ValueError("singular")
        m[c], m[p] = m[p], m[c]
        pivot = m[c][c]
        m[c] = [v / pivot for v in m[c]]
        for r in range(n):
            if r != c and m[r][c] != 0.0:
                f = m[r][c]
                m[r] = [v - f * w for v, w in zip(m[r], m[c])]
    return [row[n:] for row in m]


class Standardized:
    """열마다 평균을 빼고 흩어짐으로 나눈 학습 자료. 첫 열(상수 1)은 그대로 둡니다. 같은 눈금으로 벌금을 매기기 위해서입니다."""

    def __init__(self, rows: list[list[float]]):
        cols = list(zip(*rows))
        self.mu = [0.0] + [statistics.fmean(c) for c in cols[1:]]
        self.sd = [1.0] + [statistics.pstdev(c) or 1.0 for c in cols[1:]]
        self.z = [self.scale(r) for r in rows]
        k = len(self.mu)
        self.gram = [[sum(z[i] * z[j] for z in self.z) for j in range(k)] for i in range(k)]

    def scale(self, row: list[float]) -> list[float]:
        return [1.0] + [(v - self.mu[j]) / self.sd[j] for j, v in enumerate(row) if j > 0]


def _inverse_with_penalty(s: Standardized, lam: float) -> list[list[float]]:
    k = len(s.gram)
    return _invert([[s.gram[i][j] + (lam if i == j and i > 0 else 0.0) for j in range(k)] for i in range(k)])


def _weights(s: Standardized, inv: list[list[float]], y: list[float]) -> list[float]:
    k = len(inv)
    zty = [sum(z[i] * yy for z, yy in zip(s.z, y)) for i in range(k)]
    return [sum(inv[i][j] * zty[j] for j in range(k)) for i in range(k)]


def choose_lambda(s: Standardized, y: list[float]) -> float:
    """하루씩 빼고 맞혀 보는 오차(빼고 맞히기)가 가장 작은 벌금 세기. 한 번씩 다시 맞추지 않고 공식으로 계산합니다."""
    best, best_err = LAMBDAS[0], float("inf")
    for lam in LAMBDAS:
        try:
            inv = _inverse_with_penalty(s, lam)
        except ValueError:
            continue
        w = _weights(s, inv, y)
        err = 0.0
        for z, yy in zip(s.z, y):
            hat = sum(z[i] * sum(inv[i][j] * z[j] for j in range(len(z))) for i in range(len(z)))
            err += abs((yy - sum(a * b for a, b in zip(z, w))) / max(1.0 - hat, 1e-6))
        if err < best_err:
            best, best_err = lam, err
    return best


class Model:
    """학습한 회귀식. coef 는 원래 눈금(로그 매출 = 상수 + Σ 계수 × 값)입니다."""

    def __init__(self, rows: list[list[float]], y: list[float], lam: float | None = None):
        s = Standardized(rows)
        self.lam = lam if lam is not None else choose_lambda(s, y)
        w = _weights(s, _inverse_with_penalty(s, self.lam), y)
        self.coef = [w[j] / s.sd[j] for j in range(len(w))]
        self.coef[0] = w[0] - sum(self.coef[j] * s.mu[j] for j in range(1, len(w)))
        self.mean = s.mu
        recent = [yy - sum(c * v for c, v in zip(self.coef, row)) for row, yy in zip(rows[-LEVEL_DAYS:], y[-LEVEL_DAYS:])]
        self.shift = LEVEL_SHARE * statistics.fmean(recent) if recent else 0.0  # 최근 오차 보정(로그 단위)

    def predict(self, row: list[float]) -> float:
        return math.exp(sum(c * v for c, v in zip(self.coef, row)) + self.shift)


# ---------------------------------------------------------------- 자료 모으기
WEEKDAY_COLUMNS = list(range(1, 7))  # 화~일 (월요일이 기준)


def feature_row(day: date, labels: list[str], temp: float | None, rain_mm: float | None, with_weather: bool) -> list[float]:
    row = [1.0] + [1.0 if day.weekday() == k else 0.0 for k in WEEKDAY_COLUMNS]
    row += [1.0 if "장날" in labels else 0.0, 1.0 if any(x.startswith("공휴일") for x in labels) else 0.0, 1.0 if "방학" in labels else 0.0]
    if with_weather:
        row += [float(temp), 1.0 if rain_mm >= weather.RAIN_DAY_MM else 0.0]
    return row


def column_names(with_weather: bool) -> list[str]:
    names = ["상수"] + [f"{WEEKDAYS[k]}요일" for k in WEEKDAY_COLUMNS] + ["장날", "공휴일", "방학"]
    return names + (["기온(1도당)", "비 온 날"] if with_weather else [])


class Series:
    """예상에 쓰는 날짜별 총매출·달력·날씨."""

    def __init__(self, db: Session):
        latest = db.scalar(select(SalesUpload).order_by(SalesUpload.sales_date.desc()).limit(1))
        self.cutoff_hour = latest.cutoff_hour if latest else None
        self.latest = latest.sales_date if latest else None
        same = set(db.scalars(select(SalesUpload.sales_date).where(SalesUpload.cutoff_hour == self.cutoff_hour))) if latest else set()
        sums = db.execute(select(DailySale.sales_date, func.sum(DailySale.amount)).group_by(DailySale.sales_date)).all()
        self.totals = {d: float(t) for d, t in sums if d in same and t and t > 0}
        self.dates = sorted(self.totals)
        self.calendar = day_context.build(db)
        self.weather = weather.observed_map(db)

    def signature(self) -> str:
        parts = [str(self.cutoff_hour)] + [f"{d}:{self.totals[d]:.0f}:{','.join(self.calendar(d))}:{self.weather.get(d)}" for d in self.dates]
        return hashlib.sha1("|".join(parts).encode()).hexdigest()


# ---------------------------------------------------------------- 평소 기준
def weekday_median(series: Series, hist: list[date], day: date) -> float:
    same = [series.totals[h] for h in hist if h.weekday() == day.weekday()][-WEEKDAY_BASE_DAYS:]
    return statistics.median(same) if len(same) >= 3 else recent_median(series, hist)


def recent_median(series: Series, hist: list[date]) -> float:
    return statistics.median(series.totals[h] for h in hist[-RECENT_DAYS:])


BASELINES = {"weekday": ("같은 요일 중간값", weekday_median), "recent": ("최근 중간값(요일 구분 없음)", lambda s, h, d: recent_median(s, h))}


# ---------------------------------------------------------------- 걸러서 맞히기
def _fit_rows(series: Series, hist: list[date], with_weather: bool):
    use = [h for h in hist if h in series.weather] if with_weather else hist
    if with_weather and len(use) < SHORT_MIN_TRAIN:
        return None
    rows = [feature_row(h, series.calendar(h), *(series.weather[h] if with_weather else (None, None)), with_weather) for h in use]
    return rows, [math.log(series.totals[h]) for h in use]


def backtest(series: Series, with_weather: bool) -> dict:
    n = len(series.dates)
    start = SHORT_MIN_TRAIN if n < 40 else MIN_TRAIN
    first = max(start, n - BACKTEST_DAYS)
    errors = {"model": [], "weekday": [], "recent": []}
    lam = None
    for count, i in enumerate(range(first, n)):
        day, hist = series.dates[i], series.dates[:i]
        if with_weather and day not in series.weather:
            continue
        fitted = _fit_rows(series, hist, with_weather)
        if fitted is None:
            continue
        rows, y = fitted
        if lam is None or count % LAMBDA_EVERY == 0:
            lam = choose_lambda(Standardized(rows), y)
        model = Model(rows, y, lam)
        preds = {"model": model.predict(feature_row(day, series.calendar(day), *(series.weather[day] if with_weather else (None, None)), with_weather))}
        preds.update({k: fn(series, hist, day) for k, (_, fn) in BASELINES.items()})
        for k, p in preds.items():
            errors[k].append((p, series.totals[day]))
    return {"tests": len(errors["model"]), "errors": errors}


def _mae_pct(pairs) -> float:
    return statistics.fmean(abs(p - a) / a for p, a in pairs) * 100


def _median_pct(pairs) -> float:
    return statistics.median(abs(p - a) / a for p, a in pairs) * 100


def _quantile(values: list[float], q: float) -> float:
    v = sorted(values)
    pos = q * (len(v) - 1)
    lo, hi = math.floor(pos), math.ceil(pos)
    return v[lo] + (v[hi] - v[lo]) * (pos - lo)


_cache: dict = {}


def cached_backtest(series: Series, with_weather: bool) -> dict:
    key = (series.signature(), with_weather)
    if key not in _cache:
        if len(_cache) > 8:
            _cache.clear()
        _cache[key] = backtest(series, with_weather)
    return _cache[key]


# ---------------------------------------------------------------- 예상 만들기
def build_forecast(db: Session, request: Request | None = None) -> dict:
    series = Series(db)
    if series.latest is None:
        return {"status": "no_data"}
    target = series.latest + timedelta(days=1)
    base = {"target_date": target.isoformat(), "weekday": WEEKDAYS[target.weekday()], "cutoff_hour": series.cutoff_hour,
            "labels": series.calendar(target), "days_used": len(series.dates)}
    if len(series.dates) < MIN_DAYS:
        return {**base, "status": "not_enough", "needed_days": MIN_DAYS, "days": len(series.dates)}

    # 날씨: 이미 지난 날이면 저장된 관측값, 앞으로 올 날이면 예보, 둘 다 없으면 날씨 빠짐
    notes: list[str] = []
    w: dict | None = None
    if target in series.weather:
        t, r = series.weather[target]
        w = {"source": "observed", "temp": t, "rain_mm": r}
    elif request is not None and target >= _today():
        location, key = store_location(db), _key("WEATHER_FORECAST_API_KEY")
        if location and key:
            try:
                got = weather.fetch_forecast(_get(request), key, *location, target, _now())
                if got:
                    w = {"source": "forecast", "temp": got["temp"], "rain_mm": got["rain_mm"], "pop": got["pop"]}
            except official.OfficialError:
                notes.append("날씨 예보를 받지 못했어요.")
    with_weather = w is not None and len(series.weather) >= SHORT_MIN_TRAIN
    if w is None:
        notes.append("날씨 정보가 없어서 날씨는 반영하지 못했어요.")

    result = cached_backtest(series, with_weather)
    errors = result["errors"]
    tests = result["tests"]
    hist = series.dates
    labels = series.calendar(target)
    if not any(h.weekday() == target.weekday() for h in hist):
        notes.append(f"{WEEKDAYS[target.weekday()]}요일 매출은 한 번도 본 적이 없어서 요일 효과를 알 수 없어요.")

    # 어떤 방법을 쓸지: 모형이 평소 기준보다 꾸준히 낫지 않으면 평소 기준
    baseline_key = min(BASELINES, key=lambda k: _mae_pct(errors[k])) if tests else "weekday"
    summary = None
    use_model = False
    if tests:
        summary = {"tests": tests, "model_error_pct": round(_mae_pct(errors["model"]), 1), "baseline_error_pct": round(_mae_pct(errors[baseline_key]), 1),
                   "model_median_pct": round(_median_pct(errors["model"]), 1), "baseline_median_pct": round(_median_pct(errors[baseline_key]), 1),
                   "baseline_name": BASELINES[baseline_key][0]}
        use_model = (tests >= MIN_TEST and _mae_pct(errors["model"]) <= BEAT_MARGIN * _mae_pct(errors[baseline_key])
                     and _median_pct(errors["model"]) <= _median_pct(errors[baseline_key]))  # 평균이 5% 이상 낫고, 보통의 날 오차도 더 나쁘지 않을 때만
    method = "model" if use_model else "baseline"
    if use_model:
        fitted = _fit_rows(series, hist, with_weather)
        rows, y = fitted
        model = Model(rows, y)
        row = feature_row(target, labels, w["temp"] if with_weather else None, w["rain_mm"] if with_weather else None, with_weather)
        center = model.predict(row)
        pairs = errors["model"]
        names = column_names(with_weather)
        factors = []
        for name, coef in zip(names, model.coef):
            if name == "장날" and "장날" in labels or name == "공휴일" and any(x.startswith("공휴일") for x in labels) or name == "방학" and "방학" in labels:
                factors.append({"name": name, "effect_pct": round((math.exp(coef) - 1) * 100, 1)})
            elif name == "비 온 날" and w["rain_mm"] >= weather.RAIN_DAY_MM:
                factors.append({"name": "비 온 날", "effect_pct": round((math.exp(coef) - 1) * 100, 1)})
            elif name == "기온(1도당)":
                temp_gap = w["temp"] - model.mean[names.index(name)]
                factors.append({"name": f"기온 {w['temp']:.0f}도(학습 기간 평균 {model.mean[names.index(name)]:.0f}도 대비)", "effect_pct": round((math.exp(coef * temp_gap) - 1) * 100, 1)})
    else:
        center = BASELINES[baseline_key][1](series, hist, target)
        pairs = errors[baseline_key] if tests else []
        factors = []
        if tests >= MIN_RANGE_TEST and not use_model and tests >= MIN_TEST:
            notes.append("과거 날들로 맞혀 보니 모형이 평소 기준보다 낫다고 말할 수 없어서, 평소 기준으로 보여 드려요.")
        elif tests < MIN_TEST:
            notes.append("맞혀 볼 수 있는 날이 적어서 모형이 나은지 판단할 수 없어요. 평소 기준으로 보여 드려요.")

    low = high = None
    if len(pairs) >= MIN_RANGE_TEST:
        logs = [math.log(a / p) for p, a in pairs]
        widen = FORECAST_WIDEN if use_model and w and w["source"] == "forecast" else 1.0
        low = center * math.exp(min(_quantile(logs, 0.10), 0.0) * widen)
        high = center * math.exp(max(_quantile(logs, 0.90), 0.0) * widen)
    else:
        notes.append("범위를 말할 만큼 맞혀 본 날이 없어요.")
    return {**base, "status": "ready", "method": method, "method_name": "회귀 모형" if use_model else BASELINES[baseline_key][0],
            "center": round(center), "low": round(low) if low else None, "high": round(high) if high else None,
            "weather": w, "weather_used": bool(use_model and with_weather), "factors": factors, "backtest": summary, "notes": notes}


@router.get("/tomorrow")
def tomorrow(request: Request, db: Session = Depends(get_db)):
    return build_forecast(db, request)
