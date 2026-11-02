"""시연·시험용 "랩 DB" 만들기 (docs/lab.md).

실제 매출 데이터가 너무 적어서(월·화·수 23일), 데이터가 많을 때 화면·탐지·AI가 어떻게 동작하는지 보기 위한 가짜 데이터입니다.

- 실제 Supabase에는 **절대 쓰지 않습니다.** 별도 SQLite 파일(backend/lab/lab.db)만 만듭니다.
- **실제 날짜는 그대로 보존**하고, 빈 날짜(목~일 포함)만 가짜로 채웁니다. (가짜 날의 파일 이름은 "synthetic")
- 가짜 날의 분포는 실제 23일에서 추정합니다. 실제 근거가 없는 것(목~일의 요일 효과, 장날·공휴일 효과)은 아래 ASSUMED 의
  **가정값**이며, 이 도구로 어떤 경향도 "발견"할 수 없습니다. 연습과 시연용입니다.
- 정답이 표시된 이상(급증·급감·품절)을 넣고 DB 옆의 .truth.json (예: lab/lab.truth.json) 에 기록합니다. (탐지 평가용)
- 점주가 남긴 것처럼 보이는 운영 상황 기록도 일부 넣습니다. (이전 기록 기능 시험용)

사용법 (backend 폴더에서):
    .\\.venv\\Scripts\\python.exe tools\\make_lab_data.py
"""
import argparse
import json
import math
import random
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import mean, median, pstdev

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from sqlalchemy import select  # noqa: E402

from app.db import Base, make_engine, make_session_factory  # noqa: E402
from app.models import DailySale, ReviewedAnomaly, SalesUpload  # noqa: E402
from app.sales_file import parse_sales_csv  # noqa: E402

DEFAULT_SOURCE = BACKEND.parent / ".sl-history" / "데이터_가져오기" / "csv"
DEFAULT_OUT = BACKEND / "lab" / "lab.db"
CUTOFF_HOUR = 8

# ---------------------------------------------------------------- 가정값 (실제 근거 없음)
ASSUMED = {
    # 월~일 요일 효과(월·화·수 평균 = 1.0 기준). 월·화·수는 실제 값을 절반만 반영(작은 자료라 1쪽으로 당김), 목~일은 가정입니다.
    "weekday_multiplier_thu_to_sun": {3: 1.00, 4: 1.15, 5: 1.10, 6: 0.90},
    "market_day_multiplier": 1.08,  # 장날(3·8·13·18·23·28일)
    "holiday_multiplier_single": 0.85,
    "holiday_multiplier_long": 0.45,  # 설·추석 연휴
    "presence_multiplier_long_holiday": 0.7,  # 연휴에는 팔리는 분류 수도 줄어듦
    "shrink_real_weekday_effect": 0.5,
}

# 대략의 휴일 달력 (시연용. 정확한 공휴일표가 아닙니다)
HOLIDAYS_LONG = {
    date(2025, 10, 3): "개천절", date(2025, 10, 4): "추석 연휴", date(2025, 10, 5): "추석 연휴", date(2025, 10, 6): "추석",
    date(2025, 10, 7): "추석 연휴", date(2025, 10, 8): "대체공휴일", date(2025, 10, 9): "한글날",
    date(2026, 2, 14): "설 연휴", date(2026, 2, 15): "설 연휴", date(2026, 2, 16): "설 연휴", date(2026, 2, 17): "설날", date(2026, 2, 18): "설 연휴",
}
HOLIDAYS_SINGLE = {
    date(2025, 5, 5): "어린이날", date(2025, 5, 6): "대체공휴일", date(2025, 6, 3): "선거일", date(2025, 6, 6): "현충일",
    date(2025, 8, 15): "광복절", date(2025, 12, 25): "성탄절", date(2026, 1, 1): "신정",
}

SPIKE_WORDS = [("bulk", "회사 행사 주문"), ("promo", "할인 행사 진행"), ("bulk", "단체 구매"), ("promo", "진열 변경")]
DROP_WORDS = [("stock", "입고 지연으로 품절"), ("stock", "일부 상품 품절"), ("other", "점검으로 잠시 문을 닫음")]
AI_NOTES = [("입고가 늦었고 7시쯤 다 나갔어", "stock", "입고 지연, 품절", "7시쯤"), ("행사 물량이 한꺼번에 나갔어", "promo", "행사 물량 판매", ""), ("단체로 사 갔어", "bulk", "단체 구매", "")]


def is_market_day(d: date) -> bool:
    return d.day % 5 == 3


def holiday_of(d: date) -> tuple[str, str] | None:
    if d in HOLIDAYS_LONG:
        return "long", HOLIDAYS_LONG[d]
    if d in HOLIDAYS_SINGLE:
        return "single", HOLIDAYS_SINGLE[d]
    return None


# ---------------------------------------------------------------- 실제 자료 읽기와 분포 추정
def load_real_days(source: Path) -> dict[date, list]:
    files = sorted(source.glob("sales_*.csv"))
    if not files:
        raise SystemExit(f"실제 매출 CSV를 찾지 못했어요: {source}\n(.sl-history/데이터_가져오기/csv 에 있어야 해요)")
    days = {}
    for f in files:
        parsed = parse_sales_csv(f.read_bytes())
        days[parsed.sales_date] = (f.name, parsed.rows)
    return days


def estimate(real: dict[date, tuple[str, list]]) -> dict:
    """실제 '평범한 날'(휴일 제외)에서 분류별 분포를 추정합니다."""
    normal = {d: rows for d, (_, rows) in real.items() if holiday_of(d) is None}
    categories: dict[str, dict] = {}
    for d, rows in normal.items():
        for r in rows:
            c = categories.setdefault(r.category, {"code": r.product_code, "amounts": [], "unit": []})
            c["amounts"].append(r.amount)
            if r.amount > 0 and r.quantity > 0:
                c["unit"].append(r.amount / r.quantity)
    pooled = []
    for c in categories.values():
        pos = [math.log(a) for a in c["amounts"] if a > 0]
        c["p"] = len(pos) / len(c["amounts"])
        c["mu"] = mean(pos) if pos else 0.0
        c["sd"] = pstdev(pos) if len(pos) >= 4 else None
        c["unit_price"] = median(c["unit"]) if c["unit"] else 1000.0
        if c["sd"] is not None:
            pooled.append(c["sd"])
    fallback_sd = median(pooled) if pooled else 0.4
    for c in categories.values():
        c["sd"] = c["sd"] if c["sd"] is not None else fallback_sd
    totals = [sum(r.amount for r in rows) for rows in normal.values()]
    by_weekday: dict[int, list[int]] = {}
    for d, rows in normal.items():
        by_weekday.setdefault(d.weekday(), []).append(sum(r.amount for r in rows))
    overall = mean(totals)
    weekday_mult = {}
    for w, values in by_weekday.items():
        raw = mean(values) / overall
        weekday_mult[w] = 1 + ASSUMED["shrink_real_weekday_effect"] * (raw - 1)
    base_level = mean(weekday_mult.values())  # 실제로 있는 요일(월·화·수)의 평균을 1.0 으로
    weekday_mult = {w: m / base_level for w, m in weekday_mult.items()}
    for w, m in ASSUMED["weekday_multiplier_thu_to_sun"].items():
        weekday_mult[w] = m
    return {
        "categories": categories,
        "weekday_mult": dict(sorted(weekday_mult.items())),
        "real_total_log_sd": pstdev([math.log(t) for t in totals if t > 0]),
        "real_days": len(real),
        "normal_days": len(normal),
    }


def category_noise(params: dict, s_day: float, name: str) -> float:
    """분류 자체의 흔들림: 실제 분류 분산에서 '하루 전체 공통 흔들림'(s_day) 몫을 뺍니다."""
    return math.sqrt(max(params["categories"][name]["sd"] ** 2 - s_day**2, 0.05**2))


def simulate_total(params: dict, s_day: float, rng: random.Random, mult: float = 1.0) -> float:
    f = math.exp(rng.gauss(0, s_day)) * mult
    total = 0.0
    for name, c in params["categories"].items():
        if rng.random() < c["p"]:
            total += math.exp(c["mu"] + rng.gauss(0, category_noise(params, s_day, name))) * f
    return total


def calibrate_day_effect(params: dict, seed: int, dates: list[date]) -> tuple[float, float]:
    """합성한 '하루 총매출'의 흔들림이 실제와 비슷해지도록 하루 공통 흔들림(s_day)을 고릅니다.
    요일·장날 효과까지 포함해서 맞추고, (고른 s_day, 그때의 합성 총매출 로그 표준편차)를 돌려줍니다."""
    plain = [d for d in dates if holiday_of(d) is None]
    best, best_gap, best_sd = 0.05, 1e9, 0.0
    for s_day in [i / 100 for i in range(0, 56, 5)]:
        rng = random.Random(seed)
        sims = []
        for _ in range(2000):
            d = rng.choice(plain)
            sims.append(math.log(max(simulate_total(params, s_day, rng, day_multiplier(d, params)), 1)))
        sd = pstdev(sims)
        gap = abs(sd - params["real_total_log_sd"])
        if gap < best_gap:
            best, best_gap, best_sd = s_day, gap, sd
    return best, best_sd


# ---------------------------------------------------------------- 가짜 하루 만들기
def day_multiplier(d: date, params: dict) -> float:
    mult = params["weekday_mult"][d.weekday()]
    if is_market_day(d):
        mult *= ASSUMED["market_day_multiplier"]
    kind = holiday_of(d)
    if kind:
        mult *= ASSUMED["holiday_multiplier_long"] if kind[0] == "long" else ASSUMED["holiday_multiplier_single"]
    return mult


def synth_day(d: date, params: dict, s_day: float, rng: random.Random, events: dict[str, tuple[str, float]]) -> list[tuple[str, str, int, int]]:
    """(코드, 분류, 수량, 금액) 목록. events = {분류: (종류, 배수)} 는 정답이 표시된 이상."""
    kind = holiday_of(d)
    presence_adj = ASSUMED["presence_multiplier_long_holiday"] if kind and kind[0] == "long" else 1.0
    f = math.exp(rng.gauss(0, s_day)) * day_multiplier(d, params)
    rows = []
    for name, c in params["categories"].items():
        amount = 0.0
        if rng.random() < c["p"] * presence_adj:
            amount = math.exp(c["mu"] + rng.gauss(0, category_noise(params, s_day, name))) * f
        if name in events:
            ev_kind, factor = events[name]
            if ev_kind == "zero":
                amount = 0.0
            else:
                amount = (amount if amount > 0 else math.exp(c["mu"]) * f) * factor
        amount = int(round(amount / 50) * 50)  # 실제 금액처럼 50원 단위
        qty = max(1, round(amount / c["unit_price"])) if amount > 0 else 0
        rows.append((c["code"], name, qty, amount))
    return rows


MIN_EVENT_GAP = 8000  # 정답으로 넣는 이상은 평소와의 차이가 이 금액(원) 이상이어야 합니다. (탐지는 5,000원 미만 차이를 일부러 무시함)


def eligible(params: dict, kind: str) -> list[tuple[str, float, float, float]]:
    """종류별로 '의미 있는 크기'의 이상을 넣을 수 있는 분류와 배수 범위. (분류, 평소 금액, 최소 배수, 최대 배수)"""
    out = []
    for name, c in params["categories"].items():
        if c["p"] < 0.7:
            continue
        typical = math.exp(c["mu"])  # 팔린 날의 대략적인 금액
        if kind == "spike":
            low = max(2.5, 1 + MIN_EVENT_GAP / typical)
            if low <= 4.5:
                out.append((name, typical, low, 4.5))
        elif kind == "drop":
            high = min(0.4, 1 - MIN_EVENT_GAP / typical)
            if high >= 0.1:
                out.append((name, typical, 0.1, high))
        elif kind == "zero" and typical >= MIN_EVENT_GAP:
            out.append((name, typical, 0.0, 0.0))
    return out


def pick_events(synthetic_days: list[date], params: dict, rng: random.Random, latest: date, per_days: int = 7) -> list[dict]:
    """정답이 표시된 이상을 흩어서 넣습니다. 항상 의미 있는 금액입니다. 최근 일주일에도 몇 개를 꼭 넣어 홈에서 보이게 합니다."""
    events: list[dict] = []
    taken: set[date] = set()

    def add(d: date, kind: str):
        options = eligible(params, kind)
        if not options:
            return
        cat, typical, low, high = rng.choice(options)
        factor = 0.0 if kind == "zero" else rng.uniform(low, high)
        events.append(
            {"date": d.isoformat(), "category": cat, "kind": kind, "factor": round(factor, 2), "expected_gap": round(abs(typical * (factor - 1)))}
        )
        taken.add(d)

    recent = [d for d in synthetic_days if latest - timedelta(days=7) <= d < latest]
    for d, kind in zip(rng.sample(recent, k=min(2, len(recent))), ["spike", "drop"]):
        add(d, kind)
    older = [d for d in synthetic_days if d < latest - timedelta(days=7)]
    for d in sorted(rng.sample(older, k=max(1, len(older) // per_days))):
        if d not in taken and holiday_of(d) is None:
            add(d, rng.choices(["spike", "drop", "zero"], weights=[5, 4, 1])[0])
    return sorted(events, key=lambda e: e["date"])


# ---------------------------------------------------------------- 만들기
def build(source: Path, out: Path, start: date, seed: int) -> dict:
    real = load_real_days(source)
    params = estimate(real)
    latest = max(real)
    all_dates = [start + timedelta(days=i) for i in range((latest - start).days + 1)]
    s_day, simulated_sd = calibrate_day_effect(params, seed, all_dates)
    rng = random.Random(seed)
    synthetic_days = [d for d in all_dates if d not in real]
    events = pick_events(synthetic_days, params, rng, latest)
    events_by_day: dict[date, dict[str, tuple[str, float]]] = {}
    for e in events:
        events_by_day.setdefault(date.fromisoformat(e["date"]), {})[e["category"]] = (e["kind"], e["factor"])

    if out.exists():
        out.unlink()
    out.parent.mkdir(parents=True, exist_ok=True)
    engine = make_engine(f"sqlite:///{out}")
    Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    stamp = datetime(2026, 1, 1)
    with factory() as db:
        for d in all_dates:
            if d in real:
                filename, rows = real[d]
                data = [(r.product_code, r.category, r.quantity, r.amount) for r in rows]
            else:
                filename, data = "synthetic", synth_day(d, params, s_day, rng, events_by_day.get(d, {}))
            db.add(SalesUpload(sales_date=d, cutoff_hour=CUTOFF_HOUR, filename=filename, row_count=len(data), uploaded_at=stamp))
            db.add_all(DailySale(sales_date=d, product_code=c, category=n, quantity=q, amount=a) for c, n, q, a in data)

        # 점주가 남긴 것처럼 보이는 기록 (일주일보다 오래된 이상 중 일부). 가짜입니다.
        notes = []
        for e in events:
            d = date.fromisoformat(e["date"])
            if d >= latest - timedelta(days=7) or rng.random() > 0.7:
                continue
            if rng.random() < 0.35:
                text, reason, detail, hint = rng.choice(AI_NOTES)
                row = dict(reasons=reason, memo=detail, source="ai", raw_text=text, time_hint=hint)
            else:
                reason, memo = rng.choice(SPIKE_WORDS if e["kind"] == "spike" else DROP_WORDS)
                row = dict(reasons=reason, memo=memo, source="form", raw_text="", time_hint="")
            db.add(ReviewedAnomaly(category=e["category"], sales_date=d, reviewed_at=stamp, **row))
            notes.append({"date": e["date"], "category": e["category"], **{k: row[k] for k in ("reasons", "memo", "source")}})
        db.commit()

    meta = {
        "만든 시각": datetime.now().isoformat(timespec="seconds"),
        "seed": seed,
        "기간": [start.isoformat(), latest.isoformat()],
        "날짜 수": {"전체": len(all_dates), "실제": len(real), "가짜": len(synthetic_days)},
        "마감 시각": CUTOFF_HOUR,
        "하루 공통 흔들림(s_day, 실제 총매출 흔들림에 맞춰 고름)": s_day,
        "실제 평범한 날 총매출 로그 표준편차": round(params["real_total_log_sd"], 3),
        "가짜 평범한 날 총매출 로그 표준편차(보정 결과, 이상 제외)": round(simulated_sd, 3),
        "요일 효과(월=0 … 일=6, 월·화·수 평균=1.0)": {str(k): round(v, 3) for k, v in params["weekday_mult"].items()},
        "가정값(실제 근거 없음)": {k: (v if not isinstance(v, dict) else {str(a): b for a, b in v.items()}) for k, v in ASSUMED.items()},
        "정답이 표시된 이상": events,
        "점주 기록(가짜)": notes,
        "주의": "이 데이터로 어떤 경향도 발견할 수 없습니다. 시연과 연습용입니다.",
    }
    truth_path(out).write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta


def truth_path(db_path: Path) -> Path:
    """DB 파일마다 자기 정답 기록을 가집니다. (lab.db → lab.truth.json)"""
    return db_path.with_suffix(".truth.json")


def main() -> int:
    parser = argparse.ArgumentParser(description="시연·시험용 랩 DB 만들기")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE, help="실제 매출 CSV 폴더")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="만들 SQLite 파일 (실제 DB가 아닙니다)")
    parser.add_argument("--start", type=date.fromisoformat, default=date(2025, 5, 1), help="가짜로 채울 시작 날짜")
    parser.add_argument("--seed", type=int, default=20261029, help="같은 숫자면 같은 데이터가 만들어집니다")
    args = parser.parse_args()
    if args.out.suffix != ".db":
        raise SystemExit("--out 은 .db 파일이어야 해요. (실제 DB에는 쓰지 않습니다)")
    meta = build(args.source, args.out, args.start, args.seed)
    days = meta["날짜 수"]
    print(f"랩 DB를 만들었어요: {args.out}")
    print(f"  기간 {meta['기간'][0]} ~ {meta['기간'][1]}  (전체 {days['전체']}일 = 실제 {days['실제']}일 + 가짜 {days['가짜']}일)")
    print(f"  정답이 표시된 이상 {len(meta['정답이 표시된 이상'])}건, 가짜 점주 기록 {len(meta['점주 기록(가짜)'])}건")
    print(f"  정답 기록: {truth_path(args.out)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
