from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class AuthState(Base):
    """비밀번호와 잠금 상태. 사용자가 한 명이라 행은 항상 하나(id=1)입니다."""

    __tablename__ = "auth_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AuthSession(Base):
    """로그인 후 발급한 통행증. 원본 토큰은 저장하지 않고 해시만 저장합니다."""

    __tablename__ = "auth_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    expires_at: Mapped[datetime] = mapped_column(DateTime)


class SalesUpload(Base):
    """올린 파일 한 개 = 하루치. 날짜마다 하나만 있고, 같은 날짜를 올리면 덮어씁니다."""

    __tablename__ = "sales_uploads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sales_date: Mapped[date] = mapped_column(Date, unique=True, index=True)
    cutoff_hour: Mapped[int] = mapped_column(Integer)  # "몇 시까지의 매출인지" (0~23)
    filename: Mapped[str] = mapped_column(String(255), default="")
    row_count: Mapped[int] = mapped_column(Integer)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime)


class DailySale(Base):
    """하루치 파일의 대분류 한 줄. 파일의 "합계" 줄은 저장하지 않습니다."""

    __tablename__ = "daily_sales"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sales_date: Mapped[date] = mapped_column(Date, index=True)
    product_code: Mapped[str] = mapped_column(String(32))
    category: Mapped[str] = mapped_column(String(64))
    quantity: Mapped[int] = mapped_column(Integer)
    amount: Mapped[int] = mapped_column(BigInteger)


class ReviewedAnomaly(Base):
    """점주가 "확인함·정상"으로 답한 기록. 대분류 + 날짜 하나가 한 건입니다."""

    __tablename__ = "reviewed_anomalies"
    __table_args__ = (UniqueConstraint("category", "sales_date", name="uq_reviewed_category_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    category: Mapped[str] = mapped_column(String(64))
    sales_date: Mapped[date] = mapped_column(Date, index=True)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime)
    # 점주가 고른 당시 특이사항(쉼표로 이은 고정 키)과 메모. 점주가 직접 적은 기록이며 통계로 입증된 원인이 아닙니다.
    reasons: Mapped[str] = mapped_column(String(255), default="", server_default="")
    memo: Mapped[str] = mapped_column(String(500), default="", server_default="")
