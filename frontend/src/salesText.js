// 총매출 분석의 문구. 모든 문구는 실제 탐지 결과(test)에서 나옵니다. 금액 증감만으로 이상 여부를 정하지 않습니다.
// 원인을 단정하지 않고, 확인해 볼 일을 제안하는 말투만 씁니다.

// 한 줄 해석. tone: "check"(확인 필요, 앰버) | "plain"(차분한 안내) | "blocked"(결과를 쓸 수 없음)
export function interpret(test, diff) {
  if (test.status === "not_enough") {
    return {
      tone: "blocked",
      text: "비교할 기록이 아직 부족해요. 자료가 더 쌓이면 판매 변화를 확인할 수 있어요.",
    };
  }
  if (test.status === "no_variation") {
    return { tone: "blocked", text: "비교한 기록의 매출이 모두 같아서 변화를 판단하기 어려워요." };
  }
  if (test.verdict === "increase") {
    return {
      tone: "check",
      text: "이전 기록과 비교해 매출이 눈에 띄게 높아요. 행사나 단체 구매가 있었는지 확인해 보세요.",
    };
  }
  if (test.verdict === "decrease") {
    return {
      tone: "check",
      text: "이전 기록과 비교해 매출이 눈에 띄게 낮아요. 입고·품절이나 운영 변동이 있었는지 확인해 보세요.",
    };
  }
  if (diff > 0) return { tone: "plain", text: "매출은 늘었지만, 평소 변동 범위를 크게 벗어나지는 않았어요." };
  if (diff < 0) return { tone: "plain", text: "매출은 줄었지만, 평소 변동 범위를 크게 벗어나지는 않았어요." };
  return { tone: "plain", text: "비교 기준과 같은 수준이고, 평소 변동 범위를 벗어나지 않았어요." };
}

// 비교 기준 금액이 어떤 계산인지 (코드의 실제 계산과 같아야 합니다: 로그 기준이면 기하평균, 아니면 평균)
export function centerMethod(test) {
  return test.scale === "log"
    ? "해당 기록을 비율(%) 기준으로 평균 낸 값(기하평균)"
    : "해당 기록의 평균";
}

// 탐지 결과를 한 단어로 (분석 상세용)
export function detectionLabel(test) {
  if (test.status === "not_enough") return "자료 부족";
  if (test.status === "no_variation") return "판단 불가 (기록의 변동 없음)";
  if (test.verdict === "increase") return "상방 탐지 기준 초과";
  if (test.verdict === "decrease") return "하방 탐지 기준 초과";
  return "탐지 기준 안";
}
