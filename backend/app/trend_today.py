"""'요즘 뜨는 식품' 오늘 보기 (docs/trends.md 11장). 버튼을 누르면 편의점 신상 해시태그의 **최근 게시물**을 한 번 받아, 상품 이름별로 몇 건 언급됐는지 보여 줍니다.

- 지난주와 비교하지 않습니다(그래서 '증가'나 '뜨는 중'이라고 말하지 않고 '최근 게시물에서 많이 언급된'이라고만 합니다). 검색량도 아닙니다.
- AI 는 캡션에서 상품 이름 후보만 뽑고(trend_discover), **건수는 코드가 전체 게시물에서 다시 셉니다**. 같은 게시물은 한 번만, 같은 계정은 계정 수로 따로 셉니다.
- 하루 한 번만 받습니다. 오늘 이미 받았으면 저장된 결과를 보여 줍니다. 월 한도(APIFY_MONTHLY_RESULTS)와 한 번 실행 비용 상한(APIFY_RUN_MAX_USD)도 지킵니다.
- 회수·판매중단 같은 **안전 게시물**은 순위에 세지 않고 따로 '주의' 목록으로 보여 줍니다. 가려내는 것은 AI 가 아니라 고정된 단어 목록(SAFETY_WORDS)이라 왜 걸렸는지 설명할 수 있습니다.
  실제 회수인지는 이 게시물이 한 말일 뿐이라 확인하지 못합니다(화면에 공식 확인이 아니라고 적습니다).
- 게시물 본문은 저장하지 않습니다. 저장하는 것은 상품 이름, 건수, 근거 게시물(앞 80자 발췌·게시일·링크) 상품당 최대 5건과 주의 게시물 최대 5건뿐이고 AppSetting 한 줄이라서 새 테이블이 필요 없습니다.
"""
import json
import re
import threading
from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app import config, trend_apify, trend_discover
from app.models import AppSetting

KST = timezone(timedelta(hours=9))
KEY = "trend_today"
MIN_POSTS_SHOWN = 2  # 상품 이름이 서로 다른 게시물 2건 미만이면 보여 주지 않습니다(trend_discover.MIN_POSTS 와 같음)
# 안전 게시물 단어(띄어쓰기 무시). 놓치는 것이 과하게 걸리는 것보다 위험해서 넓게 잡습니다. 검증 전 목록이라 실제 결과를 보고 고칩니다.
# '폐기'·'환불'은 '폐기 할인', 일반 환불 안내에도 쓰여서 뺐습니다.
SAFETY_WORDS = ["회수", "판매중단", "판매중지", "부적합", "검출", "리콜", "이물질", "식중독", "대장균", "섭취중단", "섭취금지"]
MAX_WARNINGS = 5
MAX_EVIDENCE = 5  # 상품마다 보여 줄 근거 게시물 수
EMOJI_RE = re.compile("[🀀-🫿☀-➿️‍]")
SNIPPET_CHARS = 80
_lock = threading.Lock()  # 버튼을 연달아 눌러도 실행은 한 번만


def kst_today(now: datetime) -> date:
    """서버가 쓰는 UTC 시각(시간대 정보 없음)을 한국 날짜로"""
    return now.replace(tzinfo=timezone.utc).astimezone(KST).date()


def read(db: Session) -> dict | None:
    row = db.get(AppSetting, KEY)
    try:
        return json.loads(row.value) if row and row.value else None
    except json.JSONDecodeError:
        return None


def _save(db: Session, snap: dict) -> None:
    value = json.dumps(snap, ensure_ascii=False)
    row = db.get(AppSetting, KEY)
    if row is None:
        db.add(AppSetting(key=KEY, value=value))
    else:
        row.value = value
    db.commit()


def status(db: Session, ai, now: datetime | None = None) -> dict:
    """화면이 처음 받는 값: 저장된 결과와, 지금 버튼을 눌러도 되는지."""
    now = now or datetime.utcnow()
    snap = read(db)
    today = kst_today(now).isoformat()
    token = bool(config.read_env_key("APIFY_TOKEN", config.AI_ENV_FILE))
    done_today = bool(snap and snap.get("day") == today)
    lim = trend_apify.limits()
    cap_low = run_cost(lim) > lim["run_max_usd"]
    reason = None if (token and ai.state() == "ready" and not done_today and not cap_low) else ("done_today" if done_today else "no_token" if not token else "ai_unavailable" if ai.state() != "ready" else "run_cap_low")
    return {"snapshot": snap, "today": today, "can_collect": reason is None, "blocked": reason,
            "month_used": trend_apify.month_used(db, now), "monthly_limit": lim["monthly_results"], "max_results": len(trend_apify.SEEDS) * lim["per_hashtag"]}


def run_cost(lim: dict) -> float:
    """한 번 실행의 어림 최대 비용(달러). 결과 건수 × 건당 가격."""
    return len(trend_apify.SEEDS) * lim["per_hashtag"] / 1000 * trend_apify.PRICE_PER_1000


def excerpt(text: str) -> str:
    """화면에 보여 줄 짧은 발췌: 이모지를 빼고 공백을 정리해 앞 80자만."""
    return " ".join(EMOJI_RE.sub(" ", text).split())[:SNIPPET_CHARS]


def is_safety(text: str) -> bool:
    squeezed = trend_discover._squeeze(text)
    return any(w in squeezed for w in SAFETY_WORDS)


def warnings_for(safety_posts: list[dict], candidates: list[dict]) -> list[dict]:
    """안전 게시물 목록. 어떤 상품 이름이 들어 있는지는 후보 이름과 글자로 맞춰 보고, 없으면 빈 목록입니다."""
    out = []
    for p in safety_posts[:MAX_WARNINGS]:
        text = trend_discover._squeeze(p["text"])
        foods = [c["name"] for c in candidates if any(trend_discover._squeeze(n) in text for n in [c["name"], *c["aliases"]])]
        out.append({"text": excerpt(p["text"]), "url": p["url"], "posted_on": p["posted_on"], "foods": foods})
    return out


def count_foods(candidates: list[dict], posts: list[dict], safety: list[dict] = ()) -> list[dict]:
    """후보 이름(과 별칭)이 들어 있는 게시물을 전체에서 다시 세어 순위를 만듭니다. AI 가 말한 건수는 쓰지 않습니다.

    safety: 순위에 세지 않은 안전 게시물. 그 상품 이름이 들어 있는 안전 게시물 수를 `safety_posts` 로 함께 돌려줘서, 회수 소식이 있는 상품이 목록에 있어도 표시할 수 있게 합니다."""
    out = []
    for c in candidates:
        keys = [trend_discover._squeeze(n) for n in [c["name"], *c["aliases"]]]
        hit = [p for p in posts if any(k in trend_discover._squeeze(p["text"]) for k in keys)]
        accounts = {p["author"] for p in hit}
        unsafe = sum(1 for p in safety if any(k in trend_discover._squeeze(p["text"]) for k in keys))
        if len(hit) >= MIN_POSTS_SHOWN and len(accounts) >= trend_discover.MIN_ACCOUNTS:
            out.append({"name": c["name"], "aliases": c["aliases"], "posts": len(hit), "accounts": len(accounts), "safety_posts": unsafe, "evidence": [{"text": excerpt(p["text"]), "url": p["url"], "posted_on": p["posted_on"]} for p in hit if p["url"]][:MAX_EVIDENCE]})
    out.sort(key=lambda f: (-f["posts"], -f["accounts"], f["name"]))
    return out


def run(db: Session, token: str, ai, post=None, now: datetime | None = None) -> dict:
    """오늘 결과를 만듭니다. 오늘 이미 받았으면 호출하지 않고 저장된 결과를 돌려줍니다. 실패하면 ApifyError(결과는 바꾸지 않음)."""
    post = post or trend_apify.apify_post
    now = now or datetime.utcnow()
    today = kst_today(now).isoformat()
    snap = read(db)
    if snap and snap.get("day") == today:
        return snap
    if ai.state() != "ready":
        raise trend_apify.ApifyError("ai_unavailable", "AI를 쓸 수 없어서 상품 이름을 찾을 수 없어요. (게시물을 받기 전에 막아서 비용은 들지 않았어요)")
    if not _lock.acquire(blocking=False):
        raise trend_apify.ApifyError("busy", "이미 수집 중이에요.")
    try:
        lim = trend_apify.limits()
        tags = list(trend_apify.SEEDS)
        estimate = len(tags) * lim["per_hashtag"]
        if run_cost(lim) > lim["run_max_usd"]:  # 상한이 낮으면 Apify 가 중간에 멈춰 일부 해시태그만 받게 되므로, 돈을 쓰기 전에 막습니다
            raise trend_apify.ApifyError("run_cap_low", f"한 번 실행의 어림 비용(약 {run_cost(lim):.2f}달러)이 비용 상한({lim['run_max_usd']}달러)보다 커서 가져오지 않았어요. 상한(APIFY_RUN_MAX_USD)을 올리거나 해시태그당 건수를 줄여 주세요.")
        used = trend_apify.month_used(db, now)
        if used + estimate > lim["monthly_results"]:
            raise trend_apify.ApifyError("monthly_limit", f"이번 달 {used}건을 썼고 이번에 최대 {estimate}건이 더해져 월 한도({lim['monthly_results']}건)를 넘어요.")
        try:
            items = post(token, {"hashtags": tags, "resultsType": "posts", "resultsLimit": lim["per_hashtag"]},
                         {"maxItems": estimate, "maxTotalChargeUsd": lim["run_max_usd"], "timeout": trend_apify.SYNC_TIMEOUT_SECONDS})
        except trend_apify.ApifyError:
            raise
        except Exception:  # 토큰이 담길 수 있는 원문 메시지는 버리고 종류만 남깁니다
            raise trend_apify.ApifyError("network") from None
        items = [i for i in items if isinstance(i, dict)][:estimate]
        trend_apify._bump_month(db, now, len(items))
        posts, seen = [], set()
        for c in (trend_apify.to_content(i) for i in items):
            if c and c["source_id"] not in seen:
                seen.add(c["source_id"])
                posts.append({"id": len(posts) + 1, "text": c["text"], "author": c["author_key"] or c["source_id"], "url": c["url"],
                              "posted_on": c["posted_at"].replace(tzinfo=timezone.utc).astimezone(KST).date().isoformat()})
        safety = [p for p in posts if is_safety(p["text"])]
        normal = [p for p in posts if not is_safety(p["text"])]
        candidates = trend_discover.extract(ai, posts)  # 이름 찾기는 전체 글로(주의 목록에 상품 이름을 붙이려고). 건수는 아래에서 안전 글을 뺀 것만 셉니다
        snap = {"day": today, "collected_at": now.replace(microsecond=0).isoformat(), "tags": tags, "received": len(items), "unique_posts": len(posts),
                "per_hashtag": lim["per_hashtag"], "items": count_foods(candidates, normal, safety), "safety_posts": len(safety), "posted_range": [min(p["posted_on"] for p in posts), max(p["posted_on"] for p in posts)] if posts else None, "warnings": warnings_for(safety, candidates)}
        _save(db, snap)
        return snap
    finally:
        _lock.release()
