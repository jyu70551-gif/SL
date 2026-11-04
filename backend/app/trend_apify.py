"""'요즘 뜨는 식품'의 **실제 수집 코드 1호**: Apify의 공식 Instagram Hashtag Scraper로 공개 게시물을 제한적으로 모읍니다 (docs/trends.md 9장).

이 코드는 시연 데이터 공급 코드(trend_demo.py)와 별개입니다. 공급원 이름은 `instagram_apify` 이고 화면은 이 이름을 보고 "실제 수집"으로 표시합니다.

제한 (모두 환경 설정으로 바꿀 수 있고, 바꾸기 전에 비용·약관을 먼저 확인하세요)
- 공개 게시물만 모읍니다. Instagram 로그인·쿠키를 넣지 않고, 비공개 계정에 접근하지 않습니다.
- 점주가 직접 지정한 식품의 해시태그만 모읍니다. 해시태그는 APIFY_MAX_HASHTAGS(기본 8)개까지, 해시태그당 APIFY_RESULTS_PER_HASHTAG(기본 30)건까지입니다.
- 한 번 실행하는 최대 비용은 APIFY_RUN_MAX_USD(기본 0.25달러)로 막고(Apify 의 maxTotalChargeUsd), 이번 달 받은 결과 수가 APIFY_MONTHLY_RESULTS(기본 1500건)를 넘을 것 같으면 실행하지 않습니다.
- 저장하는 것은 게시물 번호(shortCode), 링크, 게시 시각, 캡션 앞부분(200자), **계정을 해시한 값**뿐입니다. 계정 이름, 이미지, 좋아요·댓글 수는 저장하지 않습니다. 30일이 지나면 지웁니다.
- 광고·협찬 표시는 이 공급원에서 알 수 없어서 표시하지 않습니다(is_ad 는 항상 거짓).
- 토큰(APIFY_TOKEN)은 요청 머리글(Authorization)로만 보내고, 오류 메시지·로그에 담지 않습니다.

수집 범위와 '모름' 처리
- Actor 는 해시태그마다 **최신 게시물**을 limit 건까지만 줍니다. 그래서 하루를 온전히 모았는지를 직접 따집니다. 실행한 날(T)이 지나간 어제(T-1)를 모읍니다.
  해시태그의 결과가 limit 건에 도달했고 가장 오래된 게시물이 그날 0시보다 늦으면, 그날 앞부분은 못 본 것이라 그날을 `capped`(상한에 걸려 일부만 수집)로 기록합니다.
  이 날은 0건이 아니라 '모름'이라서 비교와 증가 순위에서 빠집니다. 인기 해시태그는 대부분 이렇게 되므로, 이 방식은 하루 게시물이 limit 보다 적은 해시태그에만 맞습니다.
"""
import hashlib
import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app import config, trend, trend_discover
from app.models import AppSetting, TrendContent, TrendFood, TrendMention

logger = logging.getLogger("sl.trend")

SOURCE = "instagram_apify"
ACTOR_URL = "https://api.apify.com/v2/actors/apify~instagram-hashtag-scraper/run-sync-get-dataset-items"
PRICE_PER_1000 = 2.60  # 달러. Apify 공식 페이지의 무료 플랜 가격(상단 표시 최저가는 1.90달러로 다름). 어림 계산에만 씁니다.
CAPTION_CHARS = 200
RETENTION_DAYS = 30
SYNC_TIMEOUT_SECONDS = 280  # Apify 의 동기 실행은 300초를 넘으면 408 을 돌려줍니다
DEFAULTS = {"APIFY_RESULTS_PER_HASHTAG": "30", "APIFY_MAX_HASHTAGS": "8", "APIFY_RUN_MAX_USD": "0.25", "APIFY_MONTHLY_RESULTS": "1500"}


class ApifyError(Exception):
    """code 는 짧은 종류 이름입니다. 토큰이나 주소는 담지 않습니다."""

    def __init__(self, code: str, hint: str = ""):
        super().__init__(code)
        self.code = code
        self.hint = hint


def setting(name: str) -> str:
    return config.read_env_key(name, config.AI_ENV_FILE) or DEFAULTS[name]


def limits() -> dict:
    return {
        "per_hashtag": int(setting("APIFY_RESULTS_PER_HASHTAG")),
        "max_hashtags": int(setting("APIFY_MAX_HASHTAGS")),
        "run_max_usd": float(setting("APIFY_RUN_MAX_USD")),
        "monthly_results": int(setting("APIFY_MONTHLY_RESULTS")),
    }


def apify_post(token: str, body: dict, params: dict) -> list[dict]:
    """Actor 를 실행하고 결과 목록을 받습니다. 오류 메시지에 토큰이 담기지 않게 종류만 ApifyError 로 바꿉니다."""
    url = ACTOR_URL + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST",
                                     headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json", "User-Agent": "SL/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=SYNC_TIMEOUT_SECONDS + 30) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        code = {401: "unauthorized", 402: "payment", 403: "forbidden", 408: "timeout", 429: "rate_limit"}.get(error.code, "http")
        raise ApifyError(code) from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise ApifyError("network") from None
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise ApifyError("bad_response") from None
    if not isinstance(data, list):
        raise ApifyError("bad_response")
    return data


def hashtags_for(foods: list[TrendFood]) -> list[str]:
    """식품 이름과 별칭에서 해시태그(공백 없이)를 만듭니다. 중복은 한 번만."""
    tags: list[str] = []
    for food in foods:
        for name in [food.name, *json.loads(food.aliases or "[]")]:
            tag = "".join(name.split()).lstrip("#").lower()
            if tag and tag not in tags:
                tags.append(tag)
    return tags


def _month_key(now: datetime) -> str:
    return f"apify_results_{now.strftime('%Y%m')}"


def month_used(db: Session, now: datetime) -> int:
    row = db.get(AppSetting, _month_key(now))
    return int(row.value) if row and row.value.isdigit() else 0


def _kst_start(day: date) -> datetime:
    """한국 날짜 0시를 UTC naive 로"""
    return datetime(day.year, day.month, day.day, tzinfo=trend.KST).astimezone(timezone.utc).replace(tzinfo=None)


def _parse_time(text) -> datetime | None:
    try:
        return datetime.fromisoformat(str(text).replace("Z", "+00:00")).astimezone(timezone.utc).replace(tzinfo=None)
    except ValueError:
        return None


def _tag_of(item: dict) -> str:
    """결과가 어느 해시태그 검색에서 나왔는지(inputUrl 의 마지막 경로). 모르면 빈 글."""
    parts = [p for p in urllib.parse.urlparse(str(item.get("inputUrl", ""))).path.split("/") if p]
    return parts[-1].lower() if parts else ""


def to_content(item: dict) -> dict | None:
    """Apify 결과 한 건을 저장할 모양으로. 저장하는 것은 최소한뿐입니다(계정은 해시, 캡션은 앞부분)."""
    code, when = item.get("shortCode"), _parse_time(item.get("timestamp"))
    if not code or when is None:
        return None
    owner = item.get("ownerId")
    return {
        "source_id": str(code)[:60], "posted_at": when, "text": (item.get("caption") or "").strip()[:CAPTION_CHARS], "url": str(item.get("url") or f"https://www.instagram.com/p/{code}/")[:300],
        "kind": "post", "author_key": hashlib.sha256(f"ig:{owner}".encode("utf-8")).hexdigest()[:32] if owner else None, "is_repost": False, "is_ad": False,
    }


def coverage(items: list[dict], tags: list[str], limit: int, today: date) -> dict[date, str]:
    """이번 실행으로 어느 날을 온전히 모았는지. {한국 날짜: 'ok' 또는 'capped'}.

    - 상한(limit)에 닿은 해시태그가 있는데 그 가장 오래된 게시물이 어제 0시보다 늦으면, 어제 앞부분을 못 본 것이라 어제는 'capped'(모름)입니다.
    - 그렇지 않으면 어제는 'ok' 입니다.
    - 어제보다 더 이전 날은 **모든 해시태그가 상한에 닿았고** 가장 덜 거슬러 간 해시태그의 가장 오래된 시각이 그날 0시 이전일 때만 'ok' 로 칩니다.
      (상한에 안 닿은 해시태그가 얼마나 거슬러 올라갔는지는 알 수 없어서, 없던 날을 있다고 하지 않으려고 어제만 확인된 것으로 봅니다)
    """
    by_tag: dict[str, list[datetime]] = {t: [] for t in tags}
    for item in items:
        when, tag = _parse_time(item.get("timestamp")), _tag_of(item)
        if when is not None and tag in by_tag:
            by_tag[tag].append(when)
    yesterday = today - timedelta(days=1)
    capped = {t: min(times) for t, times in by_tag.items() if len(times) >= limit}
    if capped and max(capped.values()) > _kst_start(yesterday):
        return {yesterday: "capped"}
    out = {yesterday: "ok"}
    if capped and len(capped) == len(by_tag):  # 모든 해시태그가 상한까지 거슬러 올라갔을 때만 더 이전 날도 확인됨
        reach = max(capped.values())
        day = yesterday - timedelta(days=1)
        for _ in range(13):
            if _kst_start(day) >= reach:
                out[day] = "ok"
                day -= timedelta(days=1)
            else:
                break
    return out


def plan(db: Session, foods: list[TrendFood], now: datetime | None = None, per_hashtag: int | None = None) -> dict:
    """호출하기 전에 무엇을 얼마나 모을지 계산합니다. 한도를 넘으면 ApifyError."""
    now = now or datetime.utcnow()
    lim = limits()
    if per_hashtag:
        lim["per_hashtag"] = per_hashtag
    tags = hashtags_for(foods)
    if not tags:
        raise ApifyError("no_hashtags", "수집할 식품이 없어요.")
    if len(tags) > lim["max_hashtags"]:
        raise ApifyError("too_many_hashtags", f"해시태그가 {len(tags)}개라 한도({lim['max_hashtags']}개)를 넘어요. 식품을 줄이거나 한도를 바꿔 주세요.")
    max_results = len(tags) * lim["per_hashtag"]
    used = month_used(db, now)
    if used + max_results > lim["monthly_results"]:
        raise ApifyError("monthly_limit", f"이번 달 {used}건을 썼고 이번 실행으로 최대 {max_results}건이 더해져 월 한도({lim['monthly_results']}건)를 넘어요.")
    return {"tags": tags, "per_hashtag": lim["per_hashtag"], "max_results": max_results, "run_max_usd": lim["run_max_usd"], "month_used": used,
            "estimated_max_usd": round(max_results / 1000 * PRICE_PER_1000, 3)}


def purge(db: Session, now: datetime | None = None) -> int:
    """30일이 지난 이 공급원의 게시물을 지웁니다."""
    cutoff = (now or datetime.utcnow()) - timedelta(days=RETENTION_DAYS)
    ids = [i for (i,) in db.execute(select(TrendContent.id).where(TrendContent.source == SOURCE, TrendContent.posted_at < cutoff))]
    if ids:
        db.execute(delete(TrendMention).where(TrendMention.content_id.in_(ids)))
        db.execute(delete(TrendContent).where(TrendContent.id.in_(ids)))
        db.commit()
    return len(ids)


def collect(db: Session, token: str, foods: list[TrendFood], post=None, now: datetime | None = None, per_hashtag: int | None = None) -> dict:
    """지정한 식품의 해시태그로 공개 게시물을 모으고, 이번 실행으로 온전히 모은 날의 수집 상태를 기록합니다. post 는 시험에서 가짜로 바꿉니다."""
    post = post or apify_post  # 호출할 때 찾습니다(시험에서 바꿔 끼울 수 있게)
    now = now or datetime.utcnow()
    p = plan(db, foods, now, per_hashtag)
    today = trend.kst_today(now.replace(tzinfo=timezone.utc))
    try:
        items = post(token, {"hashtags": p["tags"], "resultsType": "posts", "resultsLimit": p["per_hashtag"]},
                     {"maxItems": p["max_results"], "maxTotalChargeUsd": p["run_max_usd"], "timeout": SYNC_TIMEOUT_SECONDS})
    except ApifyError:
        raise
    except Exception:  # 어떤 오류든 토큰이 담길 수 있는 원문 메시지는 버리고 종류만 남깁니다
        raise ApifyError("network") from None
    items = [i for i in items if isinstance(i, dict)][: p["max_results"]]
    contents = [c for c in (to_content(i) for i in items) if c]
    result = trend.ingest(db, SOURCE, contents, now)
    # 추적 해시태그 집합이 바뀌면 지문이 달라져 수집 범위가 달라진 것으로 보고 비교를 막습니다(새로 추적한 식품은 앞날의 자료가 없어서)
    fingerprint = hashlib.sha1("|".join(sorted(p["tags"])).encode("utf-8")).hexdigest()[:6]
    scope = f"인스타그램 공개 게시물, 해시태그 {len(p['tags'])}개({fingerprint}), 해시태그당 최대 {p['per_hashtag']}건"
    days = coverage(items, p["tags"], p["per_hashtag"], today)
    for day, status in days.items():
        trend.set_collection(db, SOURCE, day, status, scope, now)
    row = db.get(AppSetting, _month_key(now))
    total = month_used(db, now) + len(items)  # 받은 건수를 청구 건수로 어림해서 월 한도에 더합니다
    if row is None:
        db.add(AppSetting(key=_month_key(now), value=str(total)))
    else:
        row.value = str(total)
    db.commit()
    purged = purge(db, now)
    return {**p, "received": len(items), "added": result["added"], "linked": result["linked"], "days": {d.isoformat(): s for d, s in days.items()}, "purged": purged,
            "month_used": total, "scope": scope}


# ---------------------------------------------------------------- 자동 발견과 추적 (점주가 아무것도 하지 않아도 되게)
TRACKED_KEY = "apify_tracked_foods"  # 추적하는 식품 번호 목록(JSON). 이 목록의 해시태그로만 순위용 게시물을 모읍니다
SEEDS = ["편의점신상", "편의점디저트", "편의점간식"]  # 상품 이름 후보를 찾는 기본 해시태그


def tracked(db: Session) -> list[TrendFood]:
    row = db.get(AppSetting, TRACKED_KEY)
    ids = json.loads(row.value) if row and row.value else []
    found = {f.id: f for f in db.scalars(select(TrendFood).where(TrendFood.id.in_(ids)))} if ids else {}
    return [found[i] for i in ids if i in found]


def set_tracked(db: Session, foods: list[TrendFood]) -> None:
    value = json.dumps([f.id for f in foods])
    row = db.get(AppSetting, TRACKED_KEY)
    if row is None:
        db.add(AppSetting(key=TRACKED_KEY, value=value))
    else:
        row.value = value
    db.commit()


def add_tracked(db: Session, new: list[TrendFood], max_tags: int) -> list[TrendFood]:
    """추적 목록에 식품을 더합니다. 해시태그가 한도(max_tags)를 넘게 되는 식품은 더하지 않습니다(목록이 자주 바뀌면 비교가 막히므로)."""
    current = tracked(db)
    have = {f.id for f in current}
    for food in new:
        if food.id in have:
            continue
        if len(hashtags_for([*current, food])) > max_tags:
            continue
        current.append(food)
        have.add(food.id)
    set_tracked(db, current)
    return current


def _bump_month(db: Session, now: datetime, count: int) -> int:
    total = month_used(db, now) + count
    row = db.get(AppSetting, _month_key(now))
    if row is None:
        db.add(AppSetting(key=_month_key(now), value=str(total)))
    else:
        row.value = str(total)
    db.commit()
    return total


def discover(db: Session, token: str, ai, post=None, now: datetime | None = None, per_hashtag: int | None = None) -> dict:
    """기본 해시태그의 최근 게시물에서 상품 이름 후보를 찾아 스스로 추적 목록에 올립니다. 순위 계산에는 세지 않는 게시물입니다."""
    post = post or apify_post
    now = now or datetime.utcnow()
    lim = limits()
    per = per_hashtag or lim["per_hashtag"]
    current = tracked(db)
    slots = lim["max_hashtags"] - len(hashtags_for(current))
    if slots < 1:
        return {"skipped": "tracked_full", "registered": [], "tracked": [f.name for f in current]}
    estimate = len(SEEDS) * per
    if month_used(db, now) + estimate > lim["monthly_results"]:
        raise ApifyError("monthly_limit", f"발견용 {estimate}건을 더하면 월 한도({lim['monthly_results']}건)를 넘어요.")
    try:
        items = post(token, {"hashtags": SEEDS, "resultsType": "posts", "resultsLimit": per}, {"maxItems": estimate, "maxTotalChargeUsd": lim["run_max_usd"], "timeout": SYNC_TIMEOUT_SECONDS})
    except ApifyError:
        raise
    except Exception:
        raise ApifyError("network") from None
    items = [i for i in items if isinstance(i, dict)][:estimate]
    contents = [c for c in (to_content(i) for i in items) if c]
    trend.ingest(db, trend.DISCOVERY_SOURCE, contents, now)
    _bump_month(db, now, len(items))
    unique, seen = [], set()
    for n, c in enumerate(contents, 1):
        if c["source_id"] in seen:
            continue
        seen.add(c["source_id"])
        unique.append({"id": n, "text": c["text"], "author": c["author_key"] or c["source_id"]})
    candidates = trend_discover.extract(ai, unique)
    foods = trend_discover.register(db, candidates, slots)
    after = add_tracked(db, foods, lim["max_hashtags"])
    return {"received": len(items), "candidates": [{"name": c["name"], "aliases": c["aliases"], "posts": c["posts"], "accounts": c["accounts"]} for c in candidates],
            "registered": [f.name for f in foods], "tracked": [f.name for f in after]}


def auto_run(db: Session, token: str, ai, post=None, now: datetime | None = None, per_hashtag: int | None = None) -> dict:
    """점주 행동 없이: ① 추적 해시태그에 자리가 있으면 새 상품을 발견해 추적에 올리고 ② 추적 중인 식품의 해시태그로 게시물을 모읍니다."""
    now = now or datetime.utcnow()
    found = discover(db, token, ai, post, now, per_hashtag)
    foods = tracked(db)
    if not foods:
        return {"discovery": found, "collection": None}
    return {"discovery": found, "collection": collect(db, token, foods, post, now, per_hashtag)}
