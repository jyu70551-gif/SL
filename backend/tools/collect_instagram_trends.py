"""Apify 로 인스타그램 공개 게시물을 제한적으로 모읍니다 (docs/trends.md 9장). 먼저 --dry-run 으로 무엇을 얼마나 모을지 확인하세요.

⚠️ 돈이 드는 외부 호출입니다(결과 1,000건에 2~3달러 안팎). 실제 호출은 --yes 를 줘야만 합니다.
토큰은 backend/.env 의 APIFY_TOKEN 에서 읽고 화면·로그에 내지 않습니다.

사용법 (backend 폴더에서)
    # 어떤 해시태그를 얼마나 모을지, 최대 비용은 얼마인지만 보기 (호출하지 않음)
    .venv/Scripts/python tools/collect_instagram_trends.py --db lab/demo.db --food "말차 크림 도넛=말차도넛" --dry-run
    # 실제로 모으기
    .venv/Scripts/python tools/collect_instagram_trends.py --db lab/demo.db --food "말차 크림 도넛=말차도넛" --yes
    # 점주가 식품을 고르지 않아도 되는 자동 모드: 기본 해시태그에서 새 상품을 찾아 추적에 올리고, 추적 중인 식품의 게시물을 모읍니다
    .venv/Scripts/python tools/collect_instagram_trends.py --db lab/demo.db --auto --dry-run
    .venv/Scripts/python tools/collect_instagram_trends.py --db lab/demo.db --auto --yes

--food 이름[=별칭,별칭] 은 여러 번 줄 수 있고, 없는 식품은 새로 등록해 추적에 올립니다. --auto 는 식품을 주지 않아도 됩니다(자동 발견은 AI 호출이 한 번 더 듭니다). --db 는 SQLite(.db) 파일입니다.
실제 서버(Supabase)에 쓰려면 --db 대신 --supabase 를 주세요. 이 경우 먼저 alembic upgrade head(0012)가 되어 있어야 하고, 직접 실행해야 합니다.
하루에 한 번, 정해진 식품·해시태그로 모아야 비교가 이어집니다(해시태그를 바꾸면 수집 범위가 바뀌어 비교가 막힙니다).
"""
import argparse
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from sqlalchemy import select  # noqa: E402

from app import config, models, trend_apify  # noqa: E402,F401
from app.db import Base, make_engine, make_session_factory  # noqa: E402
from app.models import TrendFood  # noqa: E402


def parse_food(text: str) -> tuple[str, list[str]]:
    name, _, aliases = text.partition("=")
    return name.strip(), [a.strip() for a in aliases.split(",") if a.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description="Apify 로 인스타그램 공개 게시물을 제한적으로 모으기")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--db", type=Path, help="SQLite 파일 (.db)")
    target.add_argument("--supabase", action="store_true", help="실제 서버 DB(.env 의 DB_*)에 씁니다. 0012 가 먼저 적용돼 있어야 합니다")
    parser.add_argument("--food", action="append", default=[], help="이름[=별칭,별칭] (여러 번 가능)")
    parser.add_argument("--auto", action="store_true", help="자동 모드: 새 상품을 발견해 추적에 올리고, 추적 중인 식품의 게시물을 모읍니다")
    parser.add_argument("--limit", type=int, help="해시태그당 최대 결과 수 (기본은 설정값)")
    parser.add_argument("--dry-run", action="store_true", help="호출하지 않고 계획과 최대 비용만 보여 줍니다")
    parser.add_argument("--yes", action="store_true", help="돈이 드는 실제 호출을 허락합니다")
    args = parser.parse_args()
    if not args.food and not args.auto:
        raise SystemExit("--food 또는 --auto 중 하나는 있어야 해요.")
    if not args.dry_run and not args.yes:
        raise SystemExit("실제 호출은 비용이 듭니다. 먼저 --dry-run 으로 확인한 뒤 --yes 를 붙여 주세요.")
    if args.db:
        if args.db.suffix != ".db" or not args.db.exists():
            raise SystemExit(f"DB(.db)를 찾지 못했어요: {args.db}")
        engine = make_engine(f"sqlite:///{args.db}")
        Base.metadata.create_all(engine)
    else:
        from app.config import build_database_url
        from app.db import verify_connection, verify_migrated

        engine = make_engine(build_database_url())
        verify_connection(engine)
        verify_migrated(engine)
    token = config.read_env_key("APIFY_TOKEN", config.AI_ENV_FILE)
    if not args.dry_run and not token:
        raise SystemExit("backend/.env 에 APIFY_TOKEN 이 없어요. (값은 채팅에 붙여 넣지 말고 .env 에만 적어 주세요)")
    factory = make_session_factory(engine)
    with factory() as db:
        foods = []
        for text in args.food:
            name, aliases = parse_food(text)
            food = db.scalar(select(TrendFood).where(TrendFood.name == name, TrendFood.brand == ""))
            if food is None:
                food = TrendFood(name=name, brand="", aliases=json.dumps(aliases, ensure_ascii=False), kind="product")
                db.add(food)
                db.commit()
            foods.append(food)
        try:
            lim = trend_apify.limits()
            per = args.limit or lim["per_hashtag"]
            if foods:
                trend_apify.add_tracked(db, foods, lim["max_hashtags"])
            current = trend_apify.tracked(db)
            tags = trend_apify.hashtags_for(current)
            free = lim["max_hashtags"] - len(tags)
            discovery = args.auto and free >= 1
            max_results = (len(trend_apify.SEEDS) * per if discovery else 0) + (len(tags) + (min(free, 3) if discovery else 0)) * per
            print(f"추적 중인 식품 {len(current)}개, 해시태그 {len(tags)}개{': ' + ', '.join('#' + t for t in tags) if tags else ''}")
            if args.auto:
                print(f"자동 발견: {'기본 해시태그 ' + ', '.join('#' + t for t in trend_apify.SEEDS) + ' 에서 새 상품 찾기(자리 ' + str(free) + '개)' if discovery else '추적 자리가 가득 차서 건너뜀'}")
            print(f"해시태그당 최대 {per}건 → 이번 실행 최대 약 {max_results}건, 어림 최대 비용 약 {round(max_results / 1000 * trend_apify.PRICE_PER_1000, 3)}달러 (실행 한 번 비용 상한 {lim['run_max_usd']}달러)")
            print(f"이번 달 이미 받은 결과: {trend_apify.month_used(db, trend_apify.datetime.utcnow())}건 / 월 한도 {lim['monthly_results']}건")
            if args.dry_run:
                print("(--dry-run: 호출하지 않았어요)")
                return 0
            if args.auto:
                from app.ai.service import AiService

                result = trend_apify.auto_run(db, token, AiService(factory, env_file=config.AI_ENV_FILE), per_hashtag=args.limit)
                found = result["discovery"]
                if found.get("skipped"):
                    print("자동 발견: 건너뜀(추적 자리가 가득 참)")
                else:
                    print(f"자동 발견: 게시물 {found['received']}건에서 후보 {len(found['candidates'])}개, 새로 추적한 식품 {found['registered']}")
                    for cand in found["candidates"]:
                        print(f"  - {cand['name']} (게시물 {cand['posts']}건, 계정 {cand['accounts']}곳, 별칭 {cand['aliases']})")
                result = result["collection"]
            else:
                result = trend_apify.collect(db, token, current, per_hashtag=args.limit)
        except trend_apify.ApifyError as error:
            raise SystemExit(f"수집하지 못했어요: {error.code} {error.hint}".strip())
        if result is None:
            print("추적 중인 식품이 아직 없어서 모으지 않았어요.")
            return 0
        print(f"받은 결과 {result['received']}건, 새로 저장 {result['added']}건, 식품 연결 {result['linked']}건, 지운 오래된 게시물 {result['purged']}건")
        print(f"수집 상태 기록: {result['days']}")
        print(f"이번 달 받은 결과(어림): {result['month_used']}건")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
