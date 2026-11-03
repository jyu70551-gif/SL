"""입출고 자료로 "준비한 상품이 반복해서 얼마나 소진됐나"를 봅니다 (docs/stock.md).

판매량이 하루 늘었는지가 아니라, 그날 팔 수 있었던 수량(기초재고 + 실제 입고) 중 얼마가 팔렸고 얼마가 폐기됐는지를
최근 비교 가능한 날들에 걸쳐 반복해서 봅니다. 숫자 판단은 모두 이 코드가 하고, AI는 이 결과의 설명과 확인 질문만 씁니다.

- 소진율 = 판매 수량 ÷ (기초재고 + 입고 수량). 발주량이 아니라 실제로 팔 수 있었던 수량이 분모입니다.
- 폐기율 = 폐기 수량 ÷ (기초재고 + 입고 수량)
- 소진율 100%는 "딱 맞았다"가 아니라 "더 팔 수 있었을지도 모른다"입니다. 품절이면 판매량이 수요보다 작게 보입니다.
- 아래 PARAMS 의 값은 모두 **검증 전 초기값(제 판단)** 입니다. 상품의 소비기한·입고 주기·요일에 따라 달라져야 하고,
  가짜 자료로 동작만 확인했을 뿐 실제 점포에서 맞는지는 확인하지 않았습니다.
- 신호 이름은 "증량 필요"가 아니라 "증량 검토"입니다. 바로 많이 늘리지 않고 소량 바꿔서 확인하는 것을 전제로 합니다.
"""
import csv
import io
from dataclasses import dataclass
from datetime import date, datetime

# 검증 전 초기값. 바꿀 때는 docs/stock.md 와 docs/stats-guide.md 도 함께 고칩니다.
PARAMS = {
    "window": 5,  # 최근 비교 가능한 날 몇 번을 보는지
    "high_sell_through": 0.90,  # 이 이상이면 소진율이 높다고 봅니다
    "high_days": 4,  # window 중 이만큼 이상 높아야 "반복"
    "stockout_days": 3,  # window 중 이만큼 이상 품절 증거가 있어야 "조기 품절 반복"
    "max_waste_rate": 0.05,  # 증량 검토는 평균 폐기율이 이 이하일 때만
    "low_sell_through": 0.70,  # 이 이하이면 소진율이 낮다고 봅니다
    "waste_rate": 0.20,  # 이 이상 폐기된 날을 "폐기가 났다"고 봅니다
    "waste_days": 3,  # window 중 이만큼 이상 폐기가 나면 "폐기 반복"
    "min_available": 5,  # 그날 팔 수 있던 수량이 이 미만인 날은 근거로 쓰지 않습니다 (2개 중 2개 같은 날)
    "min_total_available": 30,  # window 전체 합이 이 미만이면 판단하지 않습니다
    "sale_end_hour": 22,  # 판매를 마치는 시각 (품절 시각을 알 때 조기 품절 판단 기준)
    "early_hours": 3,  # 판매 종료보다 이만큼 이상 일찍 품절이면 "조기 품절"
}

FIELDS = [
    "일자", "점포코드", "상품코드", "상품명", "카테고리", "기초재고", "입고수량", "매입단가", "유통기한", "공급업체",
    "판매수량", "폐기수량", "반품수량", "판매단가", "행사", "기말재고", "적정재고", "품절시각",
]


@dataclass(frozen=True)
class DayRecord:
    """상품 하나의 하루 입출고. sold_out_hour 는 품절된 시각(0~23)이고 모르면 None 입니다."""

    day: date
    product: str  # 상품 코드
    name: str
    category: str
    opening: int  # 기초재고
    received: int  # 실제 입고 수량
    sold: int
    discarded: int
    closing: int  # 기말재고
    promo: bool = False  # 행사(1+1 등) 여부
    returned: int = 0
    sold_out_hour: int | None = None

    @property
    def available(self) -> int:
        return self.opening + self.received

    @property
    def reconciles(self) -> bool:
        """기초재고 + 입고 = 판매 + 폐기 + 반품 + 기말재고 인지 (자료가 서로 맞는지). 안 맞는 줄은 판단에 쓰지 않습니다."""
        return self.opening + self.received == self.sold + self.discarded + self.returned + self.closing

    @property
    def sell_through(self) -> float | None:
        return self.sold / self.available if self.available > 0 else None

    @property
    def waste_rate(self) -> float | None:
        return self.discarded / self.available if self.available > 0 else None

    @property
    def sold_out(self) -> bool:
        """다 팔렸는지 (품절 시각을 모르는 자료에서 쓰는 추정: 기말재고 0이고 폐기도 0)"""
        return self.closing == 0 and self.discarded == 0 and self.available > 0

    def early_stockout(self) -> bool:
        """판매 종료보다 충분히 일찍 품절됐는지 (품절 시각을 아는 기록에서만 뜻이 있습니다)"""
        return self.sold_out_hour is not None and self.sold_out_hour <= PARAMS["sale_end_hour"] - PARAMS["early_hours"]


def _int(value: str, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def parse_stock_csv(text: str) -> list[DayRecord]:
    """FIELDS 의 이름으로 된 CSV 를 읽습니다. 날짜·상품코드·수량이 올바르지 않은 줄은 건너뜁니다."""
    out = []
    for row in csv.DictReader(io.StringIO(text)):
        try:
            day = date.fromisoformat((row.get("일자") or "").strip())
        except ValueError:
            continue
        code = (row.get("상품코드") or "").strip()
        if not code:
            continue
        opening, received, sold, discarded = (_int(row.get(k)) for k in ("기초재고", "입고수량", "판매수량", "폐기수량"))
        if min(opening, received, sold, discarded) < 0:
            continue
        hour = (row.get("품절시각") or "").strip()
        out.append(DayRecord(
            day=day, product=code, name=(row.get("상품명") or "").strip(), category=(row.get("카테고리") or "").strip(),
            opening=opening, received=received, sold=sold, discarded=discarded, closing=_int(row.get("기말재고")),
            promo=(row.get("행사") or "").strip() in ("1", "Y", "y", "O", "예", "true", "True"),
            returned=_int(row.get("반품수량")), sold_out_hour=int(hour) if hour.isdigit() and 0 <= int(hour) <= 23 else None,
        ))
    return out


def _brief(records: list[DayRecord]) -> dict:
    avail = sum(r.available for r in records)
    return {
        "days": len(records),
        "available": avail,
        "sold": sum(r.sold for r in records),
        "discarded": sum(r.discarded for r in records),
        "sell_through": round(sum(r.sold for r in records) / avail, 3) if avail else None,
        "waste_rate": round(sum(r.discarded for r in records) / avail, 3) if avail else None,
    }


def _day(r: DayRecord) -> dict:
    return {"day": r.day.isoformat(), "sold": r.sold, "available": r.available, "discarded": r.discarded, "promo": r.promo,
            "sold_out_hour": r.sold_out_hour, "sell_through_pct": _pct(r.sell_through), "waste_pct": _pct(r.waste_rate)}


def judge(records: list[DayRecord], as_of: date | None = None) -> dict:
    """한 상품의 기록(여러 날)으로 신호를 냅니다.

    신호: increase_review(증량 검토) / promo_only(행사 때만 소진) / decrease_review(감량·진열·구성 검토) /
          balanced(지금 수량이 맞을 가능성) / insufficient(자료 부족) / none(특별한 신호 없음)
    결과에는 판단에 쓴 날 수·수량·기준값을 모두 담아, 화면과 AI 가 같은 숫자만 말하게 합니다.
    """
    p = PARAMS
    upto = [r for r in records if as_of is None or r.day <= as_of]
    pool = sorted((r for r in upto if r.reconciles and r.available >= p["min_available"]), key=lambda r: r.day)
    # 행사 날은 판단에서 빼고(행사 때 소진율은 평소 수요가 아니라서), 행사 때만 높았는지는 따로 봅니다.
    recent = [r for r in pool if not r.promo][-p["window"]:]
    promo_recent = [r for r in pool if r.promo][-p["window"]:]
    base = {
        "params": dict(p),
        "window": _brief(recent),  # 행사가 아닌 최근 완료된 판매 주기의 합산(기간 전체 판매 ÷ 기간 전체 팔 수 있던 수량)
        "promo_window": _brief(promo_recent),  # 행사 중 판매의 합산 (행사 있는 날과 없는 날을 따로 보려고)
        "window_days": [_day(r) for r in recent],
        "promo_days": [_day(r) for r in promo_recent],
        "dropped_small_days": len([r for r in upto if r.reconciles and r.available < p["min_available"]]),
        "dropped_mismatch": len([r for r in upto if not r.reconciles]),  # 재고 수량이 서로 맞지 않아 뺀 줄
        "carryover": any(r.opening > 0 for r in recent),  # 이월 재고가 있으면 같은 상품이 여러 날 분모에 들어갑니다
    }
    if len(recent) < p["window"] or base["window"]["available"] < p["min_total_available"]:
        return {**base, "signal": "insufficient", "reasons": [f"행사 없이 판매를 마친 기록이 {len(recent)}회뿐이거나 수량이 적어서 판단하지 않아요."]}

    def high(r):
        return r.sell_through >= p["high_sell_through"]

    high_days = [r for r in recent if high(r)]
    # 품절 시각이 한 번이라도 있는 상품은 시각으로만 조기 품절을 판단합니다(마감 때 딱 맞게 다 팔린 날을 품절로 세지 않으려고).
    # 시각이 전혀 없는 상품은 "다 팔렸는지"로만 추정할 수 있어서, 그 사실을 stockout_basis 로 알립니다.
    has_hours = any(r.sold_out_hour is not None for r in recent)
    stockout_days = [r for r in recent if (r.early_stockout() if has_hours else r.sold_out)]
    waste_days = [r for r in recent if r.waste_rate >= p["waste_rate"]]
    detail = {
        "high_days": len(high_days),
        "stockout_days": len(stockout_days),
        "waste_days": len(waste_days),
        "stockout_basis": "품절 시각" if has_hours else "기말재고 0·폐기 0(추정, 일찍 품절인지는 알 수 없음)",
    }
    n = len(recent)
    if len(high_days) >= p["high_days"] and len(stockout_days) >= p["stockout_days"] and base["window"]["waste_rate"] <= p["max_waste_rate"]:
        if has_hours:
            proof = f"기록된 품절 시각이 판매 종료 {p['early_hours']}시간 전보다 이른 날이 {len(stockout_days)}번이에요."
        else:
            proof = f"다 팔린 것으로 추정되는 날이 {len(stockout_days)}번이에요. 품절 시각 기록이 없어서 마감 때 딱 맞게 다 팔린 날과 구분하지 못해요."
        reasons = [f"행사 없이 판매를 마친 최근 {n}회 중 {len(high_days)}회 소진율이 {round(p['high_sell_through'] * 100)}% 이상이었어요.", proof, "폐기는 거의 없었어요."]
        return {**base, **detail, "signal": "increase_review", "reasons": reasons}
    if len(high_days) >= p["high_days"]:
        return {**base, **detail, "signal": "balanced", "reasons": ["소진율이 높지만 일찍 품절되지는 않았어요. 폐기 비용이 적절한지는 상품 이익과 비교해 확인해 보세요."]}
    if len(waste_days) >= p["waste_days"] and base["window"]["sell_through"] <= p["low_sell_through"]:
        reasons = [f"행사 없이 판매를 마친 최근 {n}회 중 {len(waste_days)}회 폐기가 {round(p['waste_rate'] * 100)}% 이상 났고 합산 소진율이 낮았어요.",
                   "폐기가 발주 과다 때문인지 진열·상품 구성 때문인지는 이 자료만으로 알 수 없어요."]
        return {**base, **detail, "signal": "decrease_review", "reasons": reasons}
    promo_days = [r for r in pool if r.promo][-3:]  # 행사 날은 드물어서 최근 행사 3번까지 봅니다
    if len(promo_days) >= 2 and all(high(r) for r in promo_days) and len(high_days) <= 1:
        return {**base, **detail, "signal": "promo_only", "reasons": ["소진율이 높은 날이 행사 기간에만 나타났어요. 행사 중과 행사 없는 기간을 나눠 비교하고, 행사가 끝난 뒤에는 행사 없이 판매했던 기록을 참고해 보세요."]}
    return {**base, **detail, "signal": "none", "reasons": []}


def by_product(records: list[DayRecord]) -> dict[str, list[DayRecord]]:
    out: dict[str, list[DayRecord]] = {}
    for r in records:
        out.setdefault(r.product, []).append(r)
    return out


def judge_all(records: list[DayRecord], as_of: date | None = None) -> dict[str, dict]:
    """상품 코드별 judge 결과 (+ 이름·카테고리)"""
    result = {}
    for code, rows in by_product(records).items():
        result[code] = {"name": rows[-1].name, "category": rows[-1].category, **judge(rows, as_of)}
    return result


# ---------------------------------------------------------------- 저장과 화면용 요약
SIGNAL_ORDER = {"increase_review": 0, "decrease_review": 1, "promo_only": 2, "balanced": 3, "none": 4, "insufficient": 5}


def save_records(db, records: list[DayRecord]) -> int:
    """같은 날짜·상품이 이미 있으면 덮어씁니다. 저장한 줄 수를 돌려줍니다."""
    from app.models import StockDaily

    for r in records:
        db.merge(StockDaily(day=r.day, product_code=r.product, name=r.name[:60], category=r.category[:20], opening=r.opening, received=r.received,
                            sold=r.sold, discarded=r.discarded, returned=r.returned, closing=r.closing, promo=r.promo, sold_out_hour=r.sold_out_hour))
    db.commit()
    return len(records)


def load_records(db) -> list[DayRecord]:
    from sqlalchemy import select

    from app.models import StockDaily

    return [DayRecord(day=row.day, product=row.product_code, name=row.name, category=row.category, opening=row.opening, received=row.received,
                      sold=row.sold, discarded=row.discarded, closing=row.closing, promo=row.promo, returned=row.returned, sold_out_hour=row.sold_out_hour)
            for row in db.scalars(select(StockDaily).order_by(StockDaily.day))]


def _pct(value: float | None) -> int | None:
    return None if value is None else round(value * 100)


def summarize(records: list[DayRecord], now: datetime | None = None) -> dict:
    """홈 화면용 요약. 판매가 끝난 가장 최근 날짜를 기준으로 삼습니다.

    now 의 날짜와 같은 날의 기록은, 판매 종료 시각 전이면 아직 진행 중인 주기라서 판단과 소진율에 쓰지 않고 '판매 중'으로만 알립니다.
    (아침에 본 오늘 기록의 소진율이 낮다고 발주가 많았다고 볼 수 없기 때문입니다)
    """
    if not records:
        return {"status": "no_data", "products": []}
    selling_day = now.date() if now is not None and now.hour < PARAMS["sale_end_hour"] else None
    done = [r for r in records if r.day != selling_day]
    if not done:
        return {"status": "no_data", "products": []}
    as_of = max(r.day for r in done)
    items = []
    for code, rows in by_product(done).items():
        today = next((r for r in rows if r.day == as_of), None)
        verdict = judge(rows, as_of)
        w, pw = verdict["window"], verdict["promo_window"]
        live = next((r for r in records if r.product == code and r.day == selling_day), None)

        def part(b):
            return {"days": b["days"], "sold": b["sold"], "available": b["available"], "discarded": b["discarded"],
                    "sell_through_pct": _pct(b["sell_through"]), "waste_pct": _pct(b["waste_rate"])}

        items.append({
            "product": code,
            "name": rows[-1].name,
            "category": rows[-1].category,
            "signal": verdict["signal"],
            "reasons": verdict["reasons"],
            "stockout_basis": verdict.get("stockout_basis"),
            "counts": {k: verdict.get(k) for k in ("high_days", "stockout_days", "waste_days")},
            "today": None if today is None else {
                "sold": today.sold, "available": today.available, "discarded": today.discarded, "promo": today.promo,
                "sell_through_pct": _pct(today.sell_through), "waste_pct": _pct(today.waste_rate),
            },
            "selling_now": None if live is None else {"sold": live.sold},
            "window": part(w),
            "promo_window": part(pw),
            "window_days": verdict["window_days"],
            "promo_days": verdict["promo_days"],
            "carryover": verdict["carryover"],
            "dropped_mismatch": verdict["dropped_mismatch"],
        })
    items.sort(key=lambda i: (SIGNAL_ORDER[i["signal"]], i["name"]))
    return {"status": "ready", "date": as_of.isoformat(), "params": dict(PARAMS), "products": items}
