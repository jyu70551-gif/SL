from datetime import date, datetime

from sqlalchemy import BigInteger, Boolean, Date, DateTime, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.sql import expression
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
    # Phase 5-3: AI가 정리한 초안인지, 점주가 쓴 원문, 점주 말 속의 시각, 초안을 고쳐서 저장했는지
    source: Mapped[str] = mapped_column(String(8), default="form", server_default="form")
    raw_text: Mapped[str] = mapped_column(String(500), default="", server_default="")
    time_hint: Mapped[str] = mapped_column(String(30), default="", server_default="")
    ai_edited: Mapped[bool] = mapped_column(Boolean, default=False, server_default=expression.false())


class AiUsage(Base):
    """OpenAI 호출 기록. 월 한도 계산용입니다. 프롬프트·점주 글·응답 원문은 저장하지 않습니다."""

    __tablename__ = "ai_usage"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    kind: Mapped[str] = mapped_column(String(12))  # suggest (AI 제안)
    model: Mapped[str] = mapped_column(String(64), default="", server_default="")
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ok: Mapped[bool] = mapped_column(Boolean, default=False, server_default=expression.false())
    error: Mapped[str] = mapped_column(String(40), default="", server_default="")


class AiBriefing(Base):
    """날짜별 "오늘의 점검" 결과. 같은 사실이면 다시 만들지 않습니다."""

    __tablename__ = "ai_briefings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sales_date: Mapped[date] = mapped_column(Date, unique=True, index=True)
    status: Mapped[str] = mapped_column(String(10))  # pending / ok / fixed / failed
    mode: Mapped[str] = mapped_column(String(5), default="fixed", server_default="fixed")  # ai / fixed
    facts_hash: Mapped[str] = mapped_column(String(64), default="", server_default="")
    payload: Mapped[str] = mapped_column(Text, default="", server_default="")
    model: Mapped[str] = mapped_column(String(64), default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime)


class AppSetting(Base):
    """점주가 바꿀 수 있는 설정 (알림 민감도 등). 이름과 값만 저장합니다."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    value: Mapped[str] = mapped_column(String(40))


class ScheduleEvent(Base):
    """달력에 표시되는 일정. 지금은 점주가 직접 입력한 방학(kind='vacation')이고,
    이어서 공식 공휴일·학사일정이 같은 형식으로 들어옵니다. source 는 출처(owner 직접 입력 / official 공식 데이터)."""

    __tablename__ = "schedule_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(12), index=True)  # vacation / holiday / school
    name: Mapped[str] = mapped_column(String(60), default="", server_default="")
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    source: Mapped[str] = mapped_column(String(10), default="owner", server_default="owner")


class MarketDay(Base):
    """장날: 매달 이 날짜(1~31)에 장이 섭니다. 예: 3, 8, 13, 18, 23, 28"""

    __tablename__ = "market_days"

    day: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)


class WeatherDaily(Base):
    """날짜별 실제 관측 날씨 (기상청 ASOS 일자료). 내일 예상 매출 모형이 학습에 씁니다. station 은 관측소 이름(점포에서 가장 가까운 곳)."""

    __tablename__ = "weather_daily"

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    station: Mapped[str] = mapped_column(String(20), default="", server_default="")
    avg_temp: Mapped[float] = mapped_column(Float)  # 평균 기온 (℃)
    rain_mm: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")  # 일 강수량 (mm)


class StockDaily(Base):
    """상품별 하루 입출고 (docs/stock.md). 소진율·폐기율·증량 검토 신호의 재료입니다. 지금은 가짜 자료만 들어갑니다."""

    __tablename__ = "stock_daily"

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    product_code: Mapped[str] = mapped_column(String(20), primary_key=True)
    name: Mapped[str] = mapped_column(String(60), default="", server_default="")
    category: Mapped[str] = mapped_column(String(20), default="", server_default="")
    opening: Mapped[int] = mapped_column(Integer, default=0, server_default="0")  # 기초재고
    received: Mapped[int] = mapped_column(Integer, default=0, server_default="0")  # 실제 입고 수량
    sold: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    discarded: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    returned: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    closing: Mapped[int] = mapped_column(Integer, default=0, server_default="0")  # 기말재고
    promo: Mapped[bool] = mapped_column(Boolean, default=False, server_default=expression.false())  # 행사 여부
    sold_out_hour: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 품절된 시각(0~23), 모르면 비움


class TrendFood(Base):
    """'요즘 뜨는 식품' 탭의 식품 (docs/trends.md). 별칭은 JSON 글 목록이고, 같은 별칭이 둘 이상의 식품에 있으면 자동으로 연결하지 않습니다."""

    __tablename__ = "trend_foods"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(60))
    brand: Mapped[str] = mapped_column(String(40), default="", server_default="")
    aliases: Mapped[str] = mapped_column(Text, default="[]", server_default="[]")  # JSON 글 목록
    kind: Mapped[str] = mapped_column(String(10), default="type", server_default="type")  # type(식품 유형) / product(개별 상품)


class TrendContent(Base):
    """수집한 게시물·공식 발표 한 건. 공급원의 이용 조건이 허용한 글만 text 에 담습니다."""

    __tablename__ = "trend_contents"
    __table_args__ = (UniqueConstraint("source", "source_id", name="uq_trend_content_source"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(20), index=True)  # 공급원 (시연 데이터는 demo)
    source_id: Mapped[str] = mapped_column(String(60))  # 공급원 안의 원본 ID
    kind: Mapped[str] = mapped_column(String(10), default="post", server_default="post")  # post(게시물) / official(공식 발표)
    url: Mapped[str] = mapped_column(String(300), default="", server_default="")
    posted_at: Mapped[datetime] = mapped_column(DateTime)  # UTC. 집계 날짜는 한국 시간(KST)으로 바꿔서 셉니다
    collected_at: Mapped[datetime] = mapped_column(DateTime)
    text: Mapped[str] = mapped_column(Text, default="", server_default="")
    author_key: Mapped[str | None] = mapped_column(String(64), nullable=True)  # 작성 계정을 해시한 값. 모르면 비움
    dedupe_key: Mapped[str] = mapped_column(String(40), index=True)  # 같은 계정의 같은 글(복사·중복 수집)을 한 건으로 세는 열쇠
    is_repost: Mapped[bool] = mapped_column(Boolean, default=False, server_default=expression.false())  # 재게시는 세지 않습니다
    is_ad: Mapped[bool] = mapped_column(Boolean, default=False, server_default=expression.false())  # 광고·협찬 표시가 보이는 경우만


class TrendMention(Base):
    """어떤 식품의 언급으로 분류했는지 (게시물 하나가 같은 식품을 여러 번 언급해도 한 줄)"""

    __tablename__ = "trend_mentions"

    content_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    food_id: Mapped[int] = mapped_column(Integer, primary_key=True)


class TrendCollection(Base):
    """공급원·날짜별 수집 상태. 없으면 '미수집', failed 는 '수집 실패'이고 둘 다 0건이 아닙니다. scope 는 그날 수집한 범위."""

    __tablename__ = "trend_collections"

    source: Mapped[str] = mapped_column(String(20), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)  # 한국 날짜
    status: Mapped[str] = mapped_column(String(10))  # ok / failed
    scope: Mapped[str] = mapped_column(String(80), default="", server_default="")
    collected_at: Mapped[datetime] = mapped_column(DateTime)


class TrendExplanation(Base):
    """AI 설명 캐시. evidence_hash 는 설명에 쓴 근거와 지표의 지문이고, 달라지면 설명이 낡았다고 알립니다."""

    __tablename__ = "trend_explanations"

    food_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    period_end: Mapped[date] = mapped_column(Date, primary_key=True)
    evidence_hash: Mapped[str] = mapped_column(String(40))
    content_ids: Mapped[str] = mapped_column(Text, default="[]", server_default="[]")  # 사용한 근거 ID (JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    model: Mapped[str] = mapped_column(String(60), default="", server_default="")
    prompt_version: Mapped[str] = mapped_column(String(20), default="", server_default="")
    status: Mapped[str] = mapped_column(String(12))  # ok / failed / insufficient
    body: Mapped[str] = mapped_column(Text, default="{}", server_default="{}")  # 설명 JSON (검사를 통과한 것만)
    error: Mapped[str] = mapped_column(String(40), default="", server_default="")


class TrendFavorite(Base):
    """관심 식품. 사용자가 한 명이라 식품 번호만 저장합니다."""

    __tablename__ = "trend_favorites"

    food_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    saved_at: Mapped[datetime] = mapped_column(DateTime)


class AiFeedback(Base):
    """점검·초안에 대한 "도움이 됐어요 / 아니에요" 평가."""

    __tablename__ = "ai_feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    kind: Mapped[str] = mapped_column(String(10))  # briefing / draft
    ref: Mapped[str] = mapped_column(String(80))
    helpful: Mapped[bool] = mapped_column(Boolean)
