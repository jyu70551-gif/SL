"""점주가 바꾸는 설정. 지금은 알림 민감도(낮음·보통·높음)뿐입니다. 모든 주소는 비밀번호 통행증이 있어야 합니다."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.auth import get_db, require_auth
from app.detection import DEFAULT_LEVEL, LEVELS
from app.models import AppSetting

router = APIRouter(prefix="/api/settings", tags=["settings"], dependencies=[Depends(require_auth)])

SENSITIVITY_KEY = "sensitivity"
LEVEL_TEXT = {
    "low": "알림이 적게, 분명한 변화 위주로 알려요.",
    "normal": "처음 권하는 단계예요.",
    "high": "작은 변화도 일찍 알려요. 알림이 더 많아져요.",
}


def get_sensitivity(db: Session) -> str:
    """저장된 값이 없거나 알 수 없는 값이면 기본(보통)입니다."""
    row = db.get(AppSetting, SENSITIVITY_KEY)
    return row.value if row is not None and row.value in LEVELS else DEFAULT_LEVEL


class SensitivityBody(BaseModel):
    level: str


def _view(db: Session) -> dict:
    return {
        "level": get_sensitivity(db),
        "options": [{"level": key, "label": value["label"], "text": LEVEL_TEXT[key]} for key, value in LEVELS.items()],
    }


@router.get("/sensitivity")
def read_sensitivity(db: Session = Depends(get_db)):
    return _view(db)


@router.post("/sensitivity")
def change_sensitivity(body: SensitivityBody, db: Session = Depends(get_db)):
    if body.level not in LEVELS:
        raise HTTPException(status_code=422, detail={"code": "invalid_level"})
    try:
        row = db.get(AppSetting, SENSITIVITY_KEY)
        if row is None:
            db.add(AppSetting(key=SENSITIVITY_KEY, value=body.level))
        else:
            row.value = body.level
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(status_code=500, detail={"code": "save_failed"})
    return _view(db)
