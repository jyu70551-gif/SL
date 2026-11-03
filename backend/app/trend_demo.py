"""'요즘 뜨는 식품' 시연 데이터 공급 코드 (docs/trends.md). **실제 수집 코드가 아닙니다.**

실제 SNS·검색 자료를 가져오는 공급원은 아직 연결되어 있지 않아서, 화면·저장·집계·AI 설명을 시험해 볼 수 있게 가짜 게시물을 만듭니다.
- 공급원 이름은 항상 `demo` 입니다. 화면은 이 이름을 보고 "시연 데이터"를 표시합니다.
- 식품 이름, 게시물 글, 숫자는 모두 지어낸 것입니다. 실제 SNS 언급량이 아닙니다. 게시물 글 앞에는 [시연 데이터]를 붙이고 원문 링크는 두지 않습니다.
- 실제 공급원을 붙일 때는 이 파일을 쓰지 않고, 같은 모양(ingest 에 넘기는 items 와 set_collection 의 수집 상태)으로 새 수집 코드를 만듭니다.
- 심어 둔 상황: 정상 증가, 이전 기간 0건(새롭게 관측), 게시물이 적은 큰 증가율, 감소, 계정이 너무 적은 게시물 몰림, 같은 이름의 다른 브랜드(별칭 중복),
  중복·재게시·광고, 본문 없는 게시물(설명 자료 부족), 수집 실패 날(gap 옵션).
"""
import json
import random
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app import trend
from app.models import TrendCollection, TrendContent, TrendExplanation, TrendFavorite, TrendFood, TrendMention

SOURCE = "demo"
SCOPE = "시연 데이터: 가상 게시물 전체"
TAG = trend.TAG_PREFIX

# (이름, 브랜드, 별칭, 종류, 이전 기간 게시물, 현재 기간 게시물, 현재 계정 수, 공식 발표 수, 본문 형태)
FOODS = [
    ("말차 크림 도넛", "", ["말차도넛", "말차 크림도넛"], "product", 18, 51, 30, 2, "full"),
    ("치즈 크로플 샌드", "", ["치즈크로플"], "product", 0, 24, 14, 0, "full"),
    ("매운 닭강정 컵", "", ["닭강정컵"], "product", 2, 8, 6, 0, "full"),
    ("얼음 과일 컵", "", ["과일컵"], "type", 40, 22, 15, 0, "full"),
    ("고구마 말랭이 스틱", "", ["말랭이스틱"], "product", 6, 30, 3, 0, "full"),  # 계정 3곳이 30건: 순위에서 빠져야 함
    ("흑임자 푸딩", "", ["흑임자푸딩"], "product", 12, 28, 11, 0, "tag"),  # 본문이 해시태그뿐: 설명 자료 부족
    ("바삭 김부각", "가상브랜드A", ["A사 김부각"], "product", 5, 12, 6, 0, "full"),  # 별칭 "바삭 김부각"이 B 와 겹쳐서 자동 연결되지 않음
    ("바삭 김부각", "가상브랜드B", ["B사 김부각"], "product", 5, 12, 6, 0, "full"),
]

SENTENCES = {
    "말차 크림 도넛": ["{n} 먹어봤는데 겉은 쫀득하고 크림이 진하다는 후기", "{n} 편의점에서 찾았다는 글, 품절이 잦다고 언급", "{n} 달지 않고 쌉싸름해서 커피와 먹기 좋다는 게시물",
                  "{n} 주말에 사 먹을 간식으로 추천한다는 내용"],
    "치즈 크로플 샌드": ["{n} 따뜻하게 데워 먹으면 치즈가 늘어난다는 게시물", "{n} 새로 나왔다고 해서 사 봤다는 후기", "{n} 아침 대용으로 먹었다는 내용"],
    "매운 닭강정 컵": ["{n} 매운맛이 강하다고 언급한 후기", "{n} 야식으로 먹었다는 글"],
    "얼음 과일 컵": ["{n} 시원해서 낮에 사 먹었다는 후기", "{n} 컵 크기가 작다고 언급한 게시물"],
    "고구마 말랭이 스틱": ["{n} 쫀득해서 간식으로 좋다는 글", "{n} 한 봉지에 들어 있는 양을 언급한 후기"],
    "흑임자 푸딩": ["#{n}"],
    "바삭 김부각": ["{n} 바삭해서 안주로 먹었다는 후기", "{n} 짜지 않다고 언급한 게시물"],
}


def _utc(kst_day, hour: int = 12) -> datetime:
    """한국 날짜와 시각을 UTC naive 로"""
    return datetime(kst_day.year, kst_day.month, kst_day.day, hour, 0, tzinfo=trend.KST).astimezone(timezone.utc).replace(tzinfo=None)


def build_items(today, seed: int = 5) -> tuple[list[dict], list[dict]]:
    """(콘텐츠 목록, 식품 정의). 날짜는 한국 날짜 기준 최근 14일에 퍼집니다."""
    rng = random.Random(seed)
    win = trend.periods(today)
    cur_days, prev_days = trend._days(*win["current"]), trend._days(*win["previous"])
    items, seq = [], 0

    def add(text, day, author, kind="post", ad=False, repost=False, source_id=None):
        nonlocal seq
        seq += 1
        items.append({"source_id": source_id or f"demo-{seq}", "posted_at": _utc(day, rng.randint(8, 22)), "text": TAG + text if text else "", "url": "", "kind": kind,
                      "author_key": f"demo-acct-{author}", "is_repost": repost, "is_ad": ad})

    for name, brand, aliases, kind, prev_n, cur_n, cur_accts, officials, form in FOODS:
        shown = aliases[0] if brand else name
        pool = SENTENCES.get(name, ["{n} 후기"])
        for days, n, accts in ((prev_days, prev_n, max(1, prev_n // 2)), (cur_days, cur_n, cur_accts)):
            for i in range(n):
                day = days[i % len(days)]
                acct = f"{name}-{i % accts}" if (accts and days is cur_days) else f"{name}-p{i % accts}"
                sentence = pool[i % len(pool)].format(n=shown)
                # 게시물마다 글이 다르게(번호를 붙여서) 같은 계정의 글이 중복으로 합쳐지지 않게 합니다. 해시태그뿐인 글은 짧게 둡니다.
                sentence = f"{sentence} ({i + 1}번째 게시물)" if form == "full" else f"{sentence} #{i + 1}"
                add(sentence, day, acct, ad=(i % 9 == 0 and form == "full" and name == "말차 크림 도넛"))
        for k in range(officials):  # 공식 발표(확인된 계기)
            add(f"{shown} 가상 제조사가 신제품 출시를 알렸다고 가정한 공지 {k + 1}", cur_days[k], f"{name}-maker", kind="official")
    # 중복·재게시: 같은 계정의 같은 글을 한 번 더 / 재게시 표시 글
    for i in range(4):
        add("말차 크림 도넛 말차 크림 도넛 먹어봤는데 겉은 쫀득하고 크림이 진하다는 후기", cur_days[-1], "dup-1")  # 같은 계정·같은 글 4번 (한 건으로)
    for i in range(5):
        add("말차 크림 도넛 재게시", cur_days[-2], f"re-{i}", repost=True)
    # 별칭이 겹치는 모호한 글(어느 브랜드인지 몰라서 연결되지 않음)
    for i in range(6):
        add("바삭 김부각 사 먹었다는 글(브랜드는 적혀 있지 않음)", cur_days[i % len(cur_days)], f"amb-{i}")
    return items, FOODS


def load(db: Session, today=None, seed: int = 5, gap: bool = False) -> dict:
    """시연 데이터를 DB 에 넣습니다. 기존 시연 데이터는 지우고 다시 만듭니다. gap=True 면 이전 기간에 수집 실패한 날을 둡니다."""
    today = today or trend.kst_today()
    ids = [i for (i,) in db.execute(select(TrendContent.id).where(TrendContent.source == SOURCE))]
    if ids:
        db.execute(delete(TrendMention).where(TrendMention.content_id.in_(ids)))
        db.execute(delete(TrendContent).where(TrendContent.id.in_(ids)))
    db.execute(delete(TrendCollection).where(TrendCollection.source == SOURCE))
    db.execute(delete(TrendExplanation))
    db.execute(delete(TrendFavorite))
    db.execute(delete(TrendMention))
    db.execute(delete(TrendFood))
    db.flush()
    for name, brand, aliases, kind, *_ in FOODS:
        db.add(TrendFood(name=name, brand=brand, aliases=json.dumps(aliases, ensure_ascii=False), kind=kind))
    db.commit()
    items, _ = build_items(today, seed)
    result = trend.ingest(db, SOURCE, items)
    win = trend.periods(today)
    days = trend._days(win["previous"][0], win["current"][1])
    failed = {win["previous"][0] + timedelta(days=2), win["previous"][0] + timedelta(days=3)} if gap else set()
    for day in days:
        trend.set_collection(db, SOURCE, day, "failed" if day in failed else "ok", SCOPE)
    db.commit()
    return {"contents": result["added"], "links": result["linked"], "foods": len(FOODS), "failed_days": len(failed)}
