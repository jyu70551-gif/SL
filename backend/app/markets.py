"""근처 장날 가져오기 (docs/plan.md 6-2). 점포 반경 500m 안의 전통시장을 공식 데이터(전국전통시장표준데이터)에서 찾습니다.

5일장(예: 3일+8일)만 장날로 저장할 수 있습니다. 상설시장은 근처에 있다고 알려 주기만 합니다.
점주가 고른 시장의 장날만 저장되고, AI는 쓰지 않습니다. 모든 주소는 비밀번호 통행증이 있어야 합니다.
"""
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app import official
from app.auth import get_db, require_auth
from app.models import MarketDay
from app.schools import _get, _key, _unavailable
from app.settings import _save, market_days_of, store_location

router = APIRouter(prefix="/api/settings/markets", tags=["markets"], dependencies=[Depends(require_auth)])

PLACES_TTL_SECONDS = 24 * 3600
MAX_PICK = 10
_places_cache: dict = {"at": 0.0, "places": []}


def _places(request: Request) -> list[dict]:
    if _places_cache["places"] and time.monotonic() - _places_cache["at"] < PLACES_TTL_SECONDS:
        return _places_cache["places"]
    try:
        places = official.load_market_places(_get(request), _key("MARKET_API_KEY"))
    except official.OfficialError as error:
        _unavailable(error)
    _places_cache.update(at=time.monotonic(), places=places)
    return places


@router.get("")
def nearby_markets(request: Request, db: Session = Depends(get_db)):
    """점포 반경 500m 안의 시장. 위치나 키가 없으면 status 로 알려 줍니다."""
    base = {"radius_m": official.RADIUS_M, "items": [], "saved_days": market_days_of(db)}
    location = store_location(db)
    if location is None:
        return {**base, "status": "no_location"}
    if not _key("MARKET_API_KEY"):
        return {**base, "status": "no_key"}
    return {**base, "status": "ready", "items": official.nearby_markets(_places(request), *location)}


class SaveBody(BaseModel):
    market_ids: list[str] = []


@router.post("/save")
def save_market_days(body: SaveBody, request: Request, db: Session = Depends(get_db)):
    """점주가 고른 5일장의 장날로 바꿉니다. 아무것도 고르지 않으면 장날을 모두 지웁니다."""
    ids = list(dict.fromkeys(body.market_ids))
    if len(ids) > MAX_PICK:
        raise HTTPException(status_code=422, detail={"code": "invalid_markets"})
    days: set[int] = set()
    if ids:
        location = store_location(db)
        if location is None:
            raise HTTPException(status_code=422, detail={"code": "no_location"})
        near = {m["market_id"]: m for m in official.nearby_markets(_places(request), *location)}
        for market_id in ids:
            market = near.get(market_id)
            if market is None:
                raise HTTPException(status_code=404, detail={"code": "unknown_market"})
            if market["kind"] != "periodic":
                raise HTTPException(status_code=422, detail={"code": "not_periodic"})
            days.update(market["days"])
    db.execute(delete(MarketDay))
    db.add_all(MarketDay(day=d) for d in sorted(days))
    _save(db)
    return {"saved_days": market_days_of(db)}
