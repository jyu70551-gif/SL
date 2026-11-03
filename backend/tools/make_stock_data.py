"""가짜 입출고 자료 만들기 (docs/stock.md). 실제 점포 자료가 아니라, 신호 규칙이 의도대로 움직이는지 보는 연습용입니다.

상품마다 정답이 정해진 상황을 넣습니다(정답은 SCENARIOS 와 .truth.json 에 기록). 이 도구로 어떤 경향도 "발견"할 수 없고,
수요 숫자는 모두 가정입니다. 실제 DB 에는 쓰지 않고 CSV(backend/lab/stock_demo.csv)만 만듭니다.

사용법 (backend 폴더에서):
    .venv/Scripts/python tools/make_stock_data.py
"""
import argparse
import csv
import json
import random
import sys
from datetime import date, timedelta
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from app.stock import FIELDS  # noqa: E402

DEFAULT_OUT = BACKEND / "lab" / "stock_demo.csv"
START = date(2026, 9, 1)

# 상품 코드: (이름, 카테고리, 입고(=그날 팔 수 있는 수량), 평균 수요, 정답 신호)
SCENARIOS = {
    "F001": ("참치마요 삼각김밥", "간편식사", 10, 15, "increase_review"),  # 늘 모자라 일찍 품절
    "F002": ("햄치즈 샌드위치", "간편식사", 10, 9.4, "balanced"),  # 거의 다 팔리지만 일찍 품절은 아님
    "F003": ("모둠 김밥", "간편식사", 10, 4.5, "decrease_review"),  # 폐기가 반복됨
    "F004": ("행사 도시락", "즉석조리", 11, 9.0, "promo_only"),  # 평소에는 82% 안팎이고 행사 때만 다 팔림
    "F005": ("한정 디저트", "간편식사", 2, 3, "insufficient"),  # 2개 중 2개: 수량이 너무 적음
}


def build(seed: int = 3, days: int = 40, start: date = START, promo_every: int = 7) -> tuple[list[dict], dict]:
    rng = random.Random(seed)
    rows: list[dict] = []
    for i in range(days):
        day = start + timedelta(days=i)
        promo_day = i % promo_every == 6
        for code, (name, category, stock, demand, _truth) in SCENARIOS.items():
            promo = promo_day and code == "F004"
            mean = demand * (2.2 if promo else 1.0)
            want = max(0, round(rng.gauss(mean, 0.5 if code == "F004" else 1.0)))
            sold = min(stock, want)
            discarded = stock - sold if code != "F001" else 0  # 소비기한 하루: 남으면 폐기
            closing = stock - sold - discarded
            sold_out_hour = None
            if sold == stock and want > stock:
                sold_out_hour = min(22, round(8 + 14 * stock / max(want, 1)) + rng.randint(-1, 1))  # 수요가 클수록 일찍 품절
            rows.append({
                "일자": day.isoformat(), "점포코드": "S001", "상품코드": code, "상품명": name, "카테고리": category,
                "기초재고": 0, "입고수량": stock, "매입단가": 2000, "유통기한": (day + timedelta(days=1)).isoformat(), "공급업체": "가상식품",
                "판매수량": sold, "폐기수량": discarded, "반품수량": 0, "판매단가": 3000, "행사": 1 if promo else 0,
                "기말재고": closing, "적정재고": stock, "품절시각": "" if sold_out_hour is None else sold_out_hour,
            })
    truth = {code: sc[4] for code, sc in SCENARIOS.items()}
    return rows, truth


def to_csv(rows: list[dict]) -> str:
    import io

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=FIELDS, lineterminator="\r\n")
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()


def main() -> int:
    parser = argparse.ArgumentParser(description="가짜 입출고 CSV 만들기")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--seed", type=int, default=3)
    parser.add_argument("--days", type=int, default=40)
    args = parser.parse_args()
    rows, truth = build(args.seed, args.days)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(to_csv(rows), encoding="utf-8")
    args.out.with_suffix(".truth.json").write_text(json.dumps(truth, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{len(rows)}줄을 {args.out} 에 썼어요. 정답은 {args.out.with_suffix('.truth.json').name} 에 있어요.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
