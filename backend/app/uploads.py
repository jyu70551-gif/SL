"""매출 파일 올리기 (spec 2번). 두 주소 모두 비밀번호 통행증이 있어야 합니다."""
import base64
import binascii

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app import auth
from app.auth import get_db, require_auth
from app.models import DailySale, ReviewedAnomaly, SalesUpload
from app.sales_file import FileProblems, parse_sales_csv

router = APIRouter(prefix="/api/uploads", tags=["uploads"], dependencies=[Depends(require_auth)])

MAX_FILE_BYTES = 2 * 1024 * 1024


class UploadBody(BaseModel):
    filename: str = ""
    content_base64: str
    cutoff_hour: int | None = None  # 몇 시까지의 매출인지 (0~23)
    overwrite: bool = False


@router.post("")
def upload_sales_file(body: UploadBody, db: Session = Depends(get_db)):
    if body.cutoff_hour is None or not 0 <= body.cutoff_hour <= 23:
        raise HTTPException(status_code=422, detail={"code": "invalid_hour"})

    try:
        raw = base64.b64decode(body.content_base64, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_file", "problems": ["파일을 읽을 수 없어요."]},
        )
    if len(raw) > MAX_FILE_BYTES:
        raise HTTPException(status_code=413, detail={"code": "too_large"})

    try:
        parsed = parse_sales_csv(raw)
    except FileProblems as error:
        raise HTTPException(
            status_code=422, detail={"code": "invalid_file", "problems": error.problems}
        )

    existing = db.scalar(select(SalesUpload).where(SalesUpload.sales_date == parsed.sales_date))
    if existing is not None and not body.overwrite:
        # 아무것도 바꾸지 않고, 덮어쓸지 화면에서 확인받습니다.
        raise HTTPException(
            status_code=409,
            detail={
                "code": "date_exists",
                "date": parsed.sales_date.isoformat(),
                "cutoff_hour": existing.cutoff_hour,
            },
        )

    # 전부 저장되거나 전혀 저장되지 않게 한 번에 처리합니다. (spec 0-3)
    try:
        if existing is not None:
            # 덮어쓰면 이 날짜의 "확인함·정상" 기록도 지우고, 새 숫자로 이상 여부를 다시 판단합니다.
            db.execute(delete(ReviewedAnomaly).where(ReviewedAnomaly.sales_date == parsed.sales_date))
            db.execute(delete(DailySale).where(DailySale.sales_date == parsed.sales_date))
            upload = existing
        else:
            upload = SalesUpload(sales_date=parsed.sales_date)
            db.add(upload)
        upload.cutoff_hour = body.cutoff_hour
        upload.filename = body.filename[:255]
        upload.row_count = len(parsed.rows)
        upload.uploaded_at = auth.utcnow()
        db.add_all(
            DailySale(
                sales_date=parsed.sales_date,
                product_code=row.product_code,
                category=row.category,
                quantity=row.quantity,
                amount=row.amount,
            )
            for row in parsed.rows
        )
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(status_code=500, detail={"code": "save_failed"})

    return {
        "date": parsed.sales_date.isoformat(),
        "cutoff_hour": body.cutoff_hour,
        "row_count": len(parsed.rows),
        "overwritten": existing is not None,
    }


@router.get("")
def list_uploads(db: Session = Depends(get_db)):
    """올려 둔 날짜 목록 (최신 날짜가 위). 올린 데이터가 쌓이는지 볼 때 씁니다."""
    uploads = db.scalars(select(SalesUpload).order_by(SalesUpload.sales_date.desc())).all()
    return [
        {
            "date": u.sales_date.isoformat(),
            "cutoff_hour": u.cutoff_hour,
            "row_count": u.row_count,
            "uploaded_at": u.uploaded_at.isoformat() + "Z",
        }
        for u in uploads
    ]
