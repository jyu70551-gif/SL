"""'요즘 뜨는 식품' 집계와 순위 (docs/trends.md). 게시물 수·증가율·순위는 모두 이 코드가 계산하고, AI 는 숫자를 만들지 않습니다.

정의
- 언급량 = 그 식품을 언급한 **중복 제거 게시물 수**. 같은 게시물에서 여러 번(여러 별칭으로) 언급해도 한 건입니다.
  조회수·댓글·좋아요와 섞지 않고, 검색 관심도와도 별개의 지표입니다.
- 중복·재게시 처리: ① 같은 공급원의 같은 원본 ID 는 한 번만 저장합니다(DB 제약). ② 같은 계정이 같은 글을 다시 올리거나 복사 수집된 것은
  dedupe_key(계정 + 정리한 글)가 같아서 한 건으로 셉니다. ③ 재게시(공유·리트윗)로 표시된 것은 세지 않습니다.
- 한국 시간(KST) 기준으로 날짜를 셉니다. 기간은 "최근 완료된 7일"(어제까지)과 그 직전 7일입니다.
- 수집하지 못한 날은 0건이 아니라 '모름'입니다. 공급원·날짜별 수집 상태(trend_collections)에 ok 가 아닌 날이 있거나, 두 기간의 수집 범위가
  다르면 두 기간을 비교하지 않고 증가 순위에서 뺍니다(이유를 표시).
- 증가량 = 현재 기간 게시물 수 − 이전 기간 게시물 수, 증가율 = 증가량 ÷ 이전 기간 게시물 수 × 100.
  이전 기간이 0건이면 증가율은 계산하지 않고 '새롭게 관측됨'입니다.
- 관심 증가순은 **증가량**이 큰 순서입니다(증가율로 줄 세우면 2건에서 8건 같은 작은 숫자가 상위를 독점하기 때문). 같으면 증가율이 큰 쪽이 앞입니다.
- 현재 기간 게시물이 MIN_CURRENT_POSTS 미만이거나, 작성 계정 수를 아는데 MIN_CURRENT_ACCOUNTS 미만이면 증가 순위에서 뺍니다.
  이 기준값은 **검증 전 초기값(제 판단)** 이고 PARAMS 에서 바꿉니다.
- 같은 별칭이 둘 이상의 식품에 걸리면(동명·다른 브랜드의 유사 상품) 자동으로 연결하지 않습니다. 임의로 합치지 않습니다.
"""
import hashlib
import json
import re
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import TrendCollection, TrendContent, TrendFavorite, TrendFood, TrendMention

KST = timezone(timedelta(hours=9))

# 검증 전 초기값. 바꿀 때는 docs/trends.md 도 함께 고칩니다.
PARAMS = {
    "window_days": 7,  # 현재·이전 기간 길이
    "min_current_posts": 10,  # 현재 기간 게시물이 이만큼은 있어야 증가 순위에 올립니다
    "min_current_accounts": 5,  # 작성 계정 수를 알 때, 이만큼은 있어야 합니다 (한두 계정이 올린 글이 순위를 차지하지 않게)
}

SORTS = ("growth", "mentions")
DISCOVERY_SOURCE = "instagram_discovery"  # 상품 이름 후보를 찾으려고 모은 게시물. 상한에 걸려 일부만 본 것이라 게시물 수·순위 계산에는 세지 않습니다
TAG_PREFIX = "[시연 데이터] "  # 시연 데이터 게시물 글 앞에 붙는 표시. 글자 수를 셀 때는 뺍니다


def kst_today(now: datetime | None = None) -> date:
    return (now.astimezone(KST) if now and now.tzinfo else (now or datetime.now(KST))).date()


def periods(today: date) -> dict:
    """최근 완료된 N일(어제까지)과 그 직전 N일. 날짜는 모두 한국 날짜입니다."""
    n = PARAMS["window_days"]
    end = today - timedelta(days=1)
    cur = (end - timedelta(days=n - 1), end)
    prev = (cur[0] - timedelta(days=n), cur[0] - timedelta(days=1))
    return {"current": cur, "previous": prev}


def to_kst_day(utc_naive: datetime) -> date:
    return (utc_naive.replace(tzinfo=timezone.utc).astimezone(KST)).date()


def _days(start: date, end: date) -> list[date]:
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


# ---------------------------------------------------------------- 식품 연결과 저장
def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def dedupe_key(author_key: str | None, source_id: str, text: str) -> str:
    """같은 계정의 같은 글을 한 건으로 세는 열쇠. 계정을 모르면 원본 ID 로만 구분합니다(글이 같다고 합치지 않습니다)."""
    base = f"{author_key}|{_normalize(text)}" if author_key else f"id|{source_id}"
    return hashlib.sha1(base.encode("utf-8")).hexdigest()


def alias_table(foods: list[TrendFood]) -> dict[str, int | None]:
    """별칭(식품 이름 포함) → 식품 번호. 둘 이상의 식품에 걸리는 별칭은 None(모호해서 연결하지 않음)."""
    table: dict[str, int | None] = {}
    for food in foods:
        names = {food.name, *json.loads(food.aliases or "[]")}
        for name in names:
            key = _normalize(name)
            if not key:
                continue
            if key in table and table[key] != food.id:
                table[key] = None
            else:
                table[key] = food.id
    return table


def match_foods(text: str, table: dict[str, int | None]) -> set[int]:
    """글에 나온 식품 번호들. 같은 식품을 여러 번(여러 별칭으로) 언급해도 한 번만 담깁니다."""
    haystack = _normalize(text)
    squeezed = haystack.replace(" ", "")  # 해시태그는 띄어쓰기가 없어서(#말차크림도넛) 공백을 뺀 글과도 견줍니다
    return {food_id for alias, food_id in table.items() if food_id is not None and (alias in haystack or alias.replace(" ", "") in squeezed)}


def ingest(db: Session, source: str, items: list[dict], now: datetime | None = None) -> dict:
    """공급원이 가져온 콘텐츠를 저장하고 식품에 연결합니다. 이미 있는 (공급원, 원본 ID)는 건너뜁니다.

    items: {source_id, posted_at(UTC naive), text, url, kind, author_key, is_repost, is_ad}
    """
    now = now or datetime.utcnow()
    table = alias_table(list(db.scalars(select(TrendFood))))
    seen = {sid for (sid,) in db.execute(select(TrendContent.source_id).where(TrendContent.source == source))}
    added = linked = 0
    for item in items:
        if item["source_id"] in seen:
            continue
        seen.add(item["source_id"])
        text = item.get("text", "")
        content = TrendContent(
            source=source, source_id=item["source_id"], kind=item.get("kind", "post"), url=item.get("url", ""), posted_at=item["posted_at"],
            collected_at=now, text=text, author_key=item.get("author_key"), dedupe_key=dedupe_key(item.get("author_key"), item["source_id"], text),
            is_repost=bool(item.get("is_repost")), is_ad=bool(item.get("is_ad")),
        )
        db.add(content)
        db.flush()
        for food_id in match_foods(text, table):
            db.add(TrendMention(content_id=content.id, food_id=food_id))
            linked += 1
        added += 1
    db.commit()
    return {"added": added, "linked": linked}


def set_collection(db: Session, source: str, day: date, status: str, scope: str, now: datetime | None = None) -> None:
    db.merge(TrendCollection(source=source, day=day, status=status, scope=scope, collected_at=now or datetime.utcnow()))


# ---------------------------------------------------------------- 집계
def _period_state(collections: dict, sources: list[str], days: list[date]) -> dict:
    """한 기간의 수집 상태. complete 면 모든 공급원의 모든 날이 ok 입니다."""
    bad = []
    scopes = set()
    ok_days = 0
    for source in sources:
        for day in days:
            row = collections.get((source, day))
            if row is None:
                bad.append((source, day, "missing"))
            elif row.status != "ok":
                bad.append((source, day, row.status))
            else:
                ok_days += 1
                scopes.add((source, row.scope))
    return {"complete": bool(sources) and not bad, "bad": bad, "scopes": scopes, "ok_days": ok_days, "total_days": len(sources) * len(days)}


def _count(rows: list[tuple]) -> dict:
    """rows: (content, ) 중복·재게시를 걸러 센 결과"""
    keys, accounts, ads, by_source = set(), set(), set(), {}
    for c in rows:
        if c.kind == "official" or c.is_repost or c.dedupe_key in keys:  # 공식 발표는 게시물이 아니라 근거로만 씁니다
            continue
        keys.add(c.dedupe_key)
        by_source[c.source] = by_source.get(c.source, 0) + 1
        if c.author_key:
            accounts.add(c.author_key)
        if c.is_ad:
            ads.add(c.dedupe_key)
    return {"posts": len(keys), "accounts": len(accounts) if accounts else None, "ad_posts": len(ads), "by_source": by_source}


def build_summary(db: Session, today: date | None = None) -> dict:
    """탭에 보여 줄 전체 요약. 실제 집계만 담고, 설명(AI)은 따로 붙입니다."""
    today = today or kst_today()
    win = periods(today)
    cur_days, prev_days = _days(*win["current"]), _days(*win["previous"])
    foods = list(db.scalars(select(TrendFood)))
    contents = {c.id: c for c in db.scalars(select(TrendContent)) if c.source != DISCOVERY_SOURCE}
    mentions: dict[int, list[TrendContent]] = {}
    for m in db.scalars(select(TrendMention)):
        if m.content_id in contents:
            mentions.setdefault(m.food_id, []).append(contents[m.content_id])
    collections = {(c.source, c.day): c for c in db.scalars(select(TrendCollection))}
    sources = sorted({s for s, d in collections if d in set(cur_days) | set(prev_days)})
    cur_state, prev_state = _period_state(collections, sources, cur_days), _period_state(collections, sources, prev_days)
    scope_mismatch = cur_state["complete"] and prev_state["complete"] and cur_state["scopes"] != prev_state["scopes"]
    favorites = {f.food_id for f in db.scalars(select(TrendFavorite))}
    last = max((c.collected_at for c in collections.values()), default=None)
    real = [s for s in sources if s != "demo"]
    mode = "none" if not sources else "demo" if not real else "real" if len(real) == len(sources) else "mixed"

    items, excluded = {}, []
    for food in foods:
        rows = mentions.get(food.id, [])

        def in_days(days):
            ds = set(days)
            return [c for c in rows if to_kst_day(c.posted_at) in ds]

        cur, prev = _count(in_days(cur_days)), _count(in_days(prev_days))
        reason = None
        if not sources:
            reason = "수집 기록이 없어서 비교할 수 없어요."
        elif not cur_state["complete"] or not prev_state["complete"]:
            which = "최근" if not cur_state["complete"] else "직전"
            reason = f"{which} 기간에 수집하지 못한 날이 있어서 비교할 수 없어요. (못 가져온 날은 0건으로 세지 않아요)"
        elif scope_mismatch:
            reason = "두 기간의 수집 범위가 달라서 비교할 수 없어요."
        elif cur["posts"] < PARAMS["min_current_posts"]:
            reason = f"최근 게시물이 {cur['posts']}건뿐이라 순위에서 뺐어요. (기준 {PARAMS['min_current_posts']}건 이상)"
        elif cur["accounts"] is not None and cur["accounts"] < PARAMS["min_current_accounts"]:
            reason = f"작성 계정이 {cur['accounts']}곳뿐이라 순위에서 뺐어요. (기준 {PARAMS['min_current_accounts']}곳 이상)"
        change = None
        if reason is None or (cur_state["complete"] and prev_state["complete"] and not scope_mismatch):
            delta = cur["posts"] - prev["posts"]
            change = {"delta": delta, "rate_pct": None if prev["posts"] == 0 else round(delta / prev["posts"] * 100), "new": prev["posts"] == 0 and cur["posts"] > 0}

        def daily(days):
            ds = {d: 0 for d in days}
            for c in _dedupe(rows):
                if c.kind == "official":
                    continue
                d = to_kst_day(c.posted_at)
                if d in ds:
                    ds[d] += 1
            out = []
            for d in days:
                ok = all((s, d) in collections and collections[(s, d)].status == "ok" for s in sources) if sources else False
                out.append({"day": d.isoformat(), "posts": ds[d] if ok else None})  # 못 가져온 날은 None(0이 아님)
            return out

        item = {
            "food_id": food.id, "name": food.name, "brand": food.brand, "kind": food.kind, "favorite": food.id in favorites,
            "current": cur, "previous": prev, "change": change, "rank_excluded": reason, "daily": daily(cur_days + prev_days),
            "official_count": sum(1 for c in _dedupe(rows) if c.kind == "official"),
        }
        items[food.id] = item
        if reason:
            excluded.append({"food_id": food.id, "reason": reason})

    ranked = [i for i in items.values() if not i["rank_excluded"]]
    growth = sorted(ranked, key=lambda i: (-i["change"]["delta"], -(i["change"]["rate_pct"] if i["change"]["rate_pct"] is not None else 10**9), i["name"]))
    mention_ok = list(items.values()) if sources else []  # 일부만 수집됐어도 목록은 보여 주되, 화면이 "일부만 수집"이라고 표시합니다
    mention_rank = sorted(mention_ok, key=lambda i: (-i["current"]["posts"], i["name"]))
    return {
        "today": today.isoformat(),
        "period": {"current": [d.isoformat() for d in win["current"]], "previous": [d.isoformat() for d in win["previous"]]},
        "mode": mode,  # none / demo / real / mixed
        "sources": sources,
        "scope": sorted({sc for _, sc in cur_state["scopes"] | prev_state["scopes"] if sc}),
        "last_collected": last.replace(tzinfo=timezone.utc).astimezone(KST).isoformat() if last else None,
        "status": {"current": _status_view(cur_state), "previous": _status_view(prev_state), "scope_mismatch": scope_mismatch},
        "params": dict(PARAMS),
        "items": list(items.values()),
        "rank": {"growth": [i["food_id"] for i in growth], "mentions": [i["food_id"] for i in mention_rank]},
        "excluded": excluded,
    }


def _status_view(state: dict) -> dict:
    return {"complete": state["complete"], "ok_days": state["ok_days"], "total_days": state["total_days"],
            "missing_days": [d.isoformat() for s, d, st in state["bad"] if st == "missing"], "failed_days": [d.isoformat() for s, d, st in state["bad"] if st == "failed"],
            "capped_days": [d.isoformat() for s, d, st in state["bad"] if st == "capped"]}  # 상한에 걸려 일부만 수집한 날(모름)


def _dedupe(rows: list[TrendContent]) -> list[TrendContent]:
    seen, out = set(), []
    for c in rows:
        if c.is_repost or c.dedupe_key in seen:
            continue
        seen.add(c.dedupe_key)
        out.append(c)
    return out


def food_contents(db: Session, food_id: int, today: date | None = None, limit: int = 20) -> list[dict]:
    """현재 기간에 그 식품을 언급한 콘텐츠(공식 발표가 먼저, 그다음 최근 순). 중복·재게시는 뺍니다."""
    today = today or kst_today()
    start, end = periods(today)["current"]
    ids = [m.content_id for m in db.scalars(select(TrendMention).where(TrendMention.food_id == food_id))]
    rows = [c for c in db.scalars(select(TrendContent).where(TrendContent.id.in_(ids), TrendContent.source != DISCOVERY_SOURCE)) if start <= to_kst_day(c.posted_at) <= end] if ids else []
    rows = _dedupe(sorted(rows, key=lambda c: c.posted_at, reverse=True))
    rows.sort(key=lambda c: c.kind != "official")
    return [{"id": c.id, "source": c.source, "kind": c.kind, "url": c.url, "posted_on": to_kst_day(c.posted_at).isoformat(), "text": c.text, "is_ad": c.is_ad} for c in rows[:limit]]


def set_favorite(db: Session, food_id: int, on: bool, now: datetime | None = None) -> bool:
    """관심 식품을 저장·해제합니다. 없는 식품이면 False."""
    if db.get(TrendFood, food_id) is None:
        return False
    if on:
        db.merge(TrendFavorite(food_id=food_id, saved_at=now or datetime.utcnow()))
    else:
        db.execute(delete(TrendFavorite).where(TrendFavorite.food_id == food_id))
    db.commit()
    return True
