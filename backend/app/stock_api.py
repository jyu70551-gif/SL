"""소진율·폐기율·증량 검토 신호를 홈에 보여 주는 주소 (docs/stock.md). 비밀번호 통행증이 있어야 합니다.
입출고 자료는 아직 가짜 자료만 들어옵니다(tools/load_stock_csv.py). 올리는 화면은 없습니다."""
import os
from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import stock
from app.auth import get_db, require_auth

router = APIRouter(prefix="/api/stock", tags=["stock"], dependencies=[Depends(require_auth)])


@router.get("/summary")
def stock_summary(db: Session = Depends(get_db)):
    out = stock.summarize(stock.load_records(db), datetime.now())
    # 시연 서버의 가짜 상품 자료를 실제 자료로 오해하지 않게 화면이 표시할 수 있도록 알립니다.
    return {**out, "demo": os.getenv("SL_LAB_MODE") == "1"}
