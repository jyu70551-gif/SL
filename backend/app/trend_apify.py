"""'요즘 뜨는 식품' 오늘 보기가 쓰는 **Apify 호출과 한도** (docs/trends.md 9·11장).

공식 Actor `apify/instagram-hashtag-scraper` 로 해시태그의 최신 공개 게시물을 받아 옵니다. 게시물을 모아 분석하는 일은 trend_today.py 가 합니다.

제한 (모두 backend/.env 로 바꿀 수 있고, 바꾸기 전에 비용·약관을 먼저 확인하세요)
- 공개 게시물만 받습니다. Instagram 로그인·쿠키를 넣지 않고, 비공개 계정에 접근하지 않습니다.
- 해시태그당 APIFY_RESULTS_PER_HASHTAG(기본 30)건까지, 한 번 실행의 최대 비용은 APIFY_RUN_MAX_USD(기본 0.25달러, Apify 의 maxTotalChargeUsd)로 막고,
  이번 달 받은 결과 수가 APIFY_MONTHLY_RESULTS(기본 1500건)를 넘을 것 같으면 실행하지 않습니다.
- 계정은 이름이 아니라 **해시한 값**으로만 다루고, 이미지·좋아요·댓글 수는 쓰지 않습니다. 캡션은 앞 200자만 씁니다.
- 광고·협찬 표시는 이 공급원에서 알 수 없어서 표시하지 않습니다.
- 토큰(APIFY_TOKEN)은 요청 머리글(Authorization)로만 보내고, 오류 메시지·로그에 담지 않습니다.
"""
import hashlib
import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app import config
from app.models import AppSetting

ACTOR_URL = "https://api.apify.com/v2/actors/apify~instagram-hashtag-scraper/run-sync-get-dataset-items"
PRICE_PER_1000 = 2.60  # 달러. Apify 공식 페이지의 무료 플랜 가격(상단 표시 최저가는 1.90달러로 다름). 어림 계산에만 씁니다.
CAPTION_CHARS = 200
SYNC_TIMEOUT_SECONDS = 280  # Apify 의 동기 실행은 300초를 넘으면 408 을 돌려줍니다
SEEDS = ["편의점신상", "편의점디저트", "편의점간식"]  # 오늘 보기가 최근 게시물을 받는 해시태그
DEFAULTS = {"APIFY_RESULTS_PER_HASHTAG": "30", "APIFY_RUN_MAX_USD": "0.25", "APIFY_MONTHLY_RESULTS": "1500"}


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


# ---------------------------------------------------------------- 월 사용량 (받은 결과 수를 청구 건수로 어림해 더합니다)
def _month_key(now: datetime) -> str:
    return f"apify_results_{now.strftime('%Y%m')}"


def month_used(db: Session, now: datetime) -> int:
    row = db.get(AppSetting, _month_key(now))
    return int(row.value) if row and row.value.isdigit() else 0


def _bump_month(db: Session, now: datetime, count: int) -> int:
    total = month_used(db, now) + count
    row = db.get(AppSetting, _month_key(now))
    if row is None:
        db.add(AppSetting(key=_month_key(now), value=str(total)))
    else:
        row.value = str(total)
    db.commit()
    return total


# ---------------------------------------------------------------- 결과 한 건을 쓸 모양으로
def _parse_time(text) -> datetime | None:
    try:
        return datetime.fromisoformat(str(text).replace("Z", "+00:00")).astimezone(timezone.utc).replace(tzinfo=None)
    except ValueError:
        return None


def to_content(item: dict) -> dict | None:
    """Apify 결과 한 건을 쓸 모양으로. 쓰는 것은 최소한뿐입니다(계정은 해시, 캡션은 앞부분). 게시물 번호나 시각이 없으면 None."""
    code, when = item.get("shortCode"), _parse_time(item.get("timestamp"))
    if not code or when is None:
        return None
    owner = item.get("ownerId")
    return {
        "source_id": str(code)[:60], "posted_at": when, "text": (item.get("caption") or "").strip()[:CAPTION_CHARS], "url": str(item.get("url") or f"https://www.instagram.com/p/{code}/")[:300],
        "author_key": hashlib.sha256(f"ig:{owner}".encode("utf-8")).hexdigest()[:32] if owner else None,
    }
