# SL

편의점 점주를 위한 간편 통계 제공 서비스. 점주 한 명이 매출 CSV를 올리면 홈에서 오늘 매출, 평소와 다른 분류, 식품 발주 점검, 내일 예상 매출, AI 점검 요약을 보여 줍니다. (화면 React, 서버 FastAPI, 데이터 Supabase)

## 문서 읽는 순서

| 문서 | 내용 |
|---|---|
| [PRD.md](PRD.md) | 무엇을 만드는가 (기획) |
| [spec.md](spec.md) | 화면이 실제로 어떻게 동작하는가 |
| [plan.md](plan.md) | 진행 상황과 다음에 할 일 |
| **[feature-history/](feature-history/README.md)** | **기능별로 처음 설계 → 단점 → 지금 방식이 된 과정** |
| [calculation.md](calculation.md) | 계산 방식(대분류 탐지 등) |
| [stats-guide.md](stats-guide.md) | 통계 쉬운 설명서 (통계가 들어간 작업은 여기에도 씁니다) |
| [forecast-considerations.md](forecast-considerations.md) | 내일 예상 매출의 한계와 모형 선택 |
| [suggestions.md](suggestions.md) | AI 점검 요약(제안) 설계 |
| [stock.md](stock.md) | 입출고 소진율·발주 점검 |
| [trends.md](trends.md) | 요즘 뜨는 식품 (현재 방식은 11장) |
| [design.md](design.md) | 디자인 규칙 |
| [setup.md](setup.md) | 실행·설정 방법 (OpenAI·Apify 키 포함) |
| [lab.md](lab.md) | 시연(가짜) 자료와 점검 도구 |
| [mvp.md](mvp.md) | 첫 버전 범위 |
| [sdd-ai.md](sdd-ai.md) | **옛 AI 설계서(현재 구현 아님)**. 기록으로만 남김 |
| [handoff/](handoff/) | 날짜별 작업 정리(노션에 붙여넣기용)와 차트 |

## 지키는 원칙
- **코드가 계산하고 AI는 정리만 한다.** 숫자·순위·신호는 코드가 만들고, 숫자·근거 번호·단정 표현은 코드가 검사합니다.
- 실제 매출 숫자는 저장소·문서·시험에 넣지 않습니다. 가짜(시연) 자료에는 항상 표시가 붙습니다.
- 비밀 값(API 키, 토큰, 비밀번호)은 `backend/.env`에만 둡니다.
