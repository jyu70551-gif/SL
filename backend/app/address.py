"""점포 주소 검색 (카카오 로컬 API). 점주가 주소를 입력하면 후보 주소와 좌표를 돌려줍니다.

좌표는 근처 학교를 찾을 때만 쓰며 화면에는 보이지 않습니다. 인증키(KAKAO_REST_API_KEY)는 로그에 남기지 않습니다.
HTTP 호출 함수(app.state.kakao_get)는 시험에서 가짜 응답으로 바꿀 수 있습니다.
"""
import json
import urllib.error
import urllib.parse
import urllib.request

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app import config
from app.auth import require_auth

router = APIRouter(prefix="/api/settings/store", tags=["address"], dependencies=[Depends(require_auth)])

KAKAO_ADDRESS_URL = "https://dapi.kakao.com/v2/local/search/address.json"
TIMEOUT_SECONDS = 10
MAX_RESULTS = 8


class AddressError(Exception):
    """code: network / bad_response / rejected(키가 틀렸거나 카카오맵 사용 설정이 꺼져 있음)"""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def fetch_kakao(url: str, params: dict, key: str) -> dict:
    request = urllib.request.Request(
        url + "?" + urllib.parse.urlencode(params), headers={"Authorization": f"KakaoAK {key}", "User-Agent": "SL/1.0"}
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        raise AddressError("rejected" if error.code in (401, 403) else "network") from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise AddressError("network") from None
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise AddressError("bad_response") from None


def parse_documents(data: dict) -> list[dict]:
    """카카오 응답에서 {label, city, dong, latitude, longitude} 후보만 뽑습니다. 좌표가 이상한 항목은 건너뜁니다."""
    items = []
    for doc in data.get("documents") or []:
        region = doc.get("address") or doc.get("road_address") or {}
        try:
            latitude, longitude = float(doc["y"]), float(doc["x"])
        except (KeyError, TypeError, ValueError):
            continue
        label = (doc.get("road_address") or {}).get("address_name") or doc.get("address_name") or ""
        city = " ".join(p for p in (region.get("region_2depth_name"),) if p)
        dong = region.get("region_3depth_name") or ""
        if not label or not 33 <= latitude <= 39 or not 124 <= longitude <= 132:
            continue
        items.append({"label": label, "city": city, "dong": dong, "latitude": latitude, "longitude": longitude})
        if len(items) >= MAX_RESULTS:
            break
    return items


@router.get("/address")
def search_address(request: Request, q: str = Query("", max_length=100)):
    query = q.strip()
    if len(query) < 2:
        return {"status": "ready", "items": []}
    key = config.read_env_key("KAKAO_REST_API_KEY", config.AI_ENV_FILE)
    if not key:
        return {"status": "no_key", "items": []}
    get = getattr(request.app.state, "kakao_get", fetch_kakao)
    try:
        data = get(KAKAO_ADDRESS_URL, {"query": query, "size": MAX_RESULTS}, key)
    except AddressError as error:
        raise HTTPException(status_code=502, detail={"code": "address_unavailable", "reason": error.code}) from None
    return {"status": "ready", "items": parse_documents(data)}
