"""랩 DB에서 탐지가 얼마나 맞는지 세어 봅니다 (docs/lab.md, 목적 A).

- 정답이 표시된 이상(<DB 이름>.truth.json)을 대분류 탐지(`anomalies.judge`)가 몇 개 잡는지(재현율)
- 평범한 날을 잘못 잡는 정도(분류×날짜 중 몇 %, 하루에 몇 건)
- 총매출 통계 판단(t 예측구간 검정)의 "5%"가 실제로 5% 근처인지
- 점수 기준(SCORE_THRESHOLD)을 바꿔 가며 비교, 그리고 **비율(로그) 기준 점수를 쓰는 대안(실험)** 과의 비교

이 결과는 **가짜 데이터가 가진 가정(분포, 이상의 크기) 아래에서만** 의미가 있습니다. 실제 가게의 정확도가 아닙니다.
대안 점수는 이 도구 안에서만 계산하며, 앱의 탐지 코드(anomalies.py)는 바꾸지 않습니다.

사용법 (backend 폴더에서):
    .\\.venv\\Scripts\\python.exe tools\\eval_detection.py
    .\\.venv\\Scripts\\python.exe tools\\eval_detection.py --db lab\\eval_seed1.db lab\\eval_seed2.db   (여러 개를 합쳐서 셈)
"""
import argparse
import json
import math
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from statistics import median

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from sqlalchemy import func, select  # noqa: E402

from app import anomalies  # noqa: E402
from app.db import make_engine, make_session_factory  # noqa: E402
from app.models import DailySale, SalesUpload  # noqa: E402
from app.sales_detail import evaluate  # noqa: E402
from tools.make_lab_data import holiday_of  # noqa: E402

DEFAULT_DB = BACKEND / "lab" / "lab.db"
DEFAULT_THRESHOLDS = [2.0, 2.5, 3.0, 3.5, 4.0, 5.0]
ALT_THRESHOLDS = [2.0, 2.5, 3.0, 3.5, 4.0]
MIN_TOTAL_HISTORY = 30  # 총매출 검정 보정 확인은 앞선 기록이 이만큼 쌓인 날부터
ALT_OFFSET = 1000.0  # 로그를 취하기 전에 더하는 값(원). 0원인 날을 다루기 위함
ALT_SCALE_FLOOR = 0.2  # 로그 기준 흩어진 정도의 하한


def alt_flag(amount: int, history: list[int], threshold: float) -> bool:
    """대안(실험): 금액 차이 대신 **비율(로그)** 차이로 점수를 냅니다. 5,000원 이상 차이 조건은 그대로 둡니다."""
    logs = [math.log(h + ALT_OFFSET) for h in history]
    center = median(logs)
    mad = median(abs(v - center) for v in logs)
    scale = max(1.4826 * mad, ALT_SCALE_FLOOR)
    score = (math.log(amount + ALT_OFFSET) - center) / scale
    return abs(score) >= threshold and abs(amount - median(history)) >= anomalies.MIN_AMOUNT_GAP


def evaluate_rule(db, files: dict[date, str], truth: list[dict], thresholds: list[float], mode: str) -> list[dict]:
    """mode: 'current'(앱의 현재 점수) 또는 'alt'(비율 기준 대안). 결과는 점수 기준마다 한 줄."""
    events = {(e["category"], date.fromisoformat(e["date"])): e for e in truth}
    data = anomalies._analyze(db, anomalies.LEGACY)
    amounts = anomalies._amounts_by_date(db)
    judged, weeks_used = data["judged"], data["weeks_used"]
    original = anomalies.SCORE_THRESHOLD
    results = []
    try:
        for threshold in thresholds:
            anomalies.SCORE_THRESHOLD = threshold
            if mode == "current":
                judged_now = anomalies._analyze(db, anomalies.LEGACY)["judged"]

            def flagged(cat: str, d: date) -> bool:
                entry = judged[(cat, d)]
                history = [amounts.get(date.fromisoformat(x), {}).get(cat, 0) for x in entry["baseline_dates"]]
                _, sparse = anomalies.baseline_of(history)
                if mode == "current" or sparse:  # 거의 늘 0원인 분류는 대안에서도 현재 방식 그대로
                    return (judged_now if mode == "current" else judged_current)[(cat, d)]["anomaly"] is not None
                return alt_flag(entry["amount"], history, threshold)

            if mode == "alt":
                anomalies.SCORE_THRESHOLD = original
                judged_current = anomalies._analyze(db, anomalies.LEGACY)["judged"]

            judgeable = {k: e for k, e in events.items() if weeks_used.get(k[1], 0) >= anomalies.MIN_SAME_WEEKDAY_DAYS}
            hit = {k for k in judgeable if flagged(*k)}
            by_kind = defaultdict(lambda: [0, 0])
            for k, e in judgeable.items():
                by_kind[e["kind"]][1] += 1
                by_kind[e["kind"]][0] += k in hit
            false_alarms = real_alarms = holiday_alarms = cells = 0
            plain_days = set()
            for (cat, d) in judged:
                if weeks_used.get(d, 0) < anomalies.MIN_SAME_WEEKDAY_DAYS:
                    continue
                if holiday_of(d) is not None:
                    holiday_alarms += flagged(cat, d)
                    continue
                if (cat, d) in events:
                    continue
                if files[d] == "synthetic":
                    cells += 1
                    plain_days.add(d)
                    false_alarms += flagged(cat, d)
                else:
                    real_alarms += flagged(cat, d)
            results.append(
                {
                    "threshold": threshold,
                    "events": len(judgeable),
                    "hit": len(hit),
                    "by_kind": {k: tuple(v) for k, v in by_kind.items()},
                    "cells": cells,
                    "false_alarms": false_alarms,
                    "plain_days": len(plain_days),
                    "real_alarms": real_alarms,
                    "holiday_alarms": holiday_alarms,
                }
            )
    finally:
        anomalies.SCORE_THRESHOLD = original
    return results


def merge(per_db: list[list[dict]]) -> list[dict]:
    """여러 랩 DB의 같은 점수 기준 결과를 합칩니다. (비율은 합친 개수로 다시 계산)"""
    merged = []
    for index, first in enumerate(per_db[0]):
        group = [run[index] for run in per_db]
        by_kind = defaultdict(lambda: [0, 0])
        for r in group:
            for kind, (h, n) in r["by_kind"].items():
                by_kind[kind][0] += h
                by_kind[kind][1] += n
        events, hit = sum(r["events"] for r in group), sum(r["hit"] for r in group)
        cells, alarms, days = sum(r["cells"] for r in group), sum(r["false_alarms"] for r in group), sum(r["plain_days"] for r in group)
        merged.append(
            {
                "threshold": first["threshold"],
                "recall": hit / events if events else 0.0,
                "by_kind": {k: tuple(v) for k, v in by_kind.items()},
                "cell_rate": alarms / cells if cells else 0.0,
                "per_day": alarms / days if days else 0.0,
                "real_alarms": sum(r["real_alarms"] for r in group) / len(group),  # 같은 실제 23일을 DB마다 세므로 평균
                "holiday_alarms": sum(r["holiday_alarms"] for r in group) / len(group),
            }
        )
    return merged


def total_test_calibration(db, files: dict[date, str], truth: list[dict]) -> dict:
    """총매출 t 검정이 평범한 날에 "탐지 기준 초과"로 나오는 비율. 이론상 5% 근처여야 합니다."""
    totals = {d: int(a) for d, a in db.execute(select(DailySale.sales_date, func.sum(DailySale.amount)).group_by(DailySale.sales_date))}
    ordered = sorted(totals)
    event_days = {e["date"] for e in truth}
    flagged = checked = 0
    for index, d in enumerate(ordered):
        if index < MIN_TOTAL_HISTORY or files[d] != "synthetic" or holiday_of(d) is not None or d.isoformat() in event_days:
            continue
        result = evaluate([totals[x] for x in ordered[:index]], totals[d])
        if result["status"] != "ready":
            continue
        checked += 1
        flagged += result["verdict"] != "none"
    return {"checked": checked, "flagged": flagged}


def print_table(title: str, rows: list[dict], current: float | None) -> None:
    print(title)
    print(f"{'점수 기준':>8} {'재현율':>7} {'급증':>9} {'급감':>9} {'품절(0원)':>10} | {'오경보(분류×날짜)':>16} {'하루 평균':>8} | {'실제 날 경보':>10} {'휴일 경보':>8}")
    for r in rows:
        k = r["by_kind"]
        cell = lambda name: f"{k[name][0]}/{k[name][1]}" if name in k else "-"
        mark = "  ← 현재" if current is not None and r["threshold"] == current else ""
        print(
            f"{r['threshold']:>8.1f} {r['recall']*100:>6.0f}% {cell('spike'):>9} {cell('drop'):>9} {cell('zero'):>10} | "
            f"{r['cell_rate']*100:>15.2f}% {r['per_day']:>8.2f} | {r['real_alarms']:>10.1f} {r['holiday_alarms']:>8.1f}{mark}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="랩 DB 탐지 평가")
    parser.add_argument("--db", type=Path, nargs="+", default=[DEFAULT_DB], help="여러 개를 주면 합쳐서 셉니다 (시드를 바꿔 여러 번 만든 랩 DB)")
    parser.add_argument("--thresholds", type=float, nargs="+", default=DEFAULT_THRESHOLDS)
    parser.add_argument("--no-alt", action="store_true", help="비율(로그) 기준 대안 비교를 건너뜁니다")
    args = parser.parse_args()

    current_runs, alt_runs, calibrations = [], [], []
    for db_path in args.db:
        truth_path = db_path.with_suffix(".truth.json")
        if not db_path.exists() or not truth_path.exists():
            raise SystemExit(f"랩 DB나 정답 기록이 없어요: {db_path}\n먼저 tools/make_lab_data.py 를 실행해 주세요.")
        truth = json.loads(truth_path.read_text(encoding="utf-8"))["정답이 표시된 이상"]
        factory = make_session_factory(make_engine(f"sqlite:///{db_path}"))
        with factory() as db:
            files = {u.sales_date: u.filename for u in db.scalars(select(SalesUpload))}
            current_runs.append(evaluate_rule(db, files, truth, args.thresholds, "current"))
            if not args.no_alt:
                alt_runs.append(evaluate_rule(db, files, truth, ALT_THRESHOLDS, "alt"))
            calibrations.append(total_test_calibration(db, files, truth))

    events = sum(run[0]["events"] for run in current_runs)
    print(f"랩 DB {len(args.db)}개, 판단 가능한 정답 이상 {events}건 (가짜 날짜만)\n")
    print_table("== [현재] 금액 차이 기준 점수 (anomalies.py 와 같음)", merge(current_runs), anomalies.SCORE_THRESHOLD)
    if alt_runs:
        print()
        print_table("== [실험] 비율(로그) 기준 점수 — 같은 5,000원 이상 조건, 거의 늘 0원인 분류는 현재 방식", merge(alt_runs), None)
    checked, flagged = sum(c["checked"] for c in calibrations), sum(c["flagged"] for c in calibrations)
    rate = flagged / checked * 100 if checked else 0.0
    print(f"\n== 총매출 통계 판단(t 예측구간 검정): 평범한 날을 '탐지 기준 초과'로 잡는 비율 (이론상 약 5%)")
    print(f"   검사한 날 {checked}일 중 {flagged}일 = {rate:.1f}%")
    print("\n※ 가짜 데이터의 가정 아래에서의 결과입니다. 실제 가게의 정확도가 아닙니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
