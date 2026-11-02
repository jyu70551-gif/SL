// 운영 상황 기록의 선택 항목. 점주가 직접 고른 기록이며 통계로 입증된 원인이 아닙니다. (서버 anomalies.py 의 REASONS 와 같아야 합니다)
export const REASONS = [
  ["promo", "행사·진열 변경"],
  ["bulk", "단체 구매"],
  ["stock", "입고·품절 관련 사항"],
  ["data_check", "데이터 확인 필요"],
  ["other", "기타"],
  ["unknown", "모르겠어요"],
  ["none", "특이사항 없음"], // "정상"이 아니라 "점주가 확인해 특이사항 없음으로 답함"
];

export const SOLO = ["unknown", "none"]; // 다른 선택과 함께 저장할 수 없는 값
export const STORE = "__store__"; // 분류에 속하지 않는 점포 전체 기록

export const reasonLabel = (key) => REASONS.find(([k]) => k === key)?.[1] ?? key;

// 체크박스를 눌렀을 때의 다음 선택 목록. "모르겠어요"와 "특이사항 없음"은 단독으로만 남습니다.
export function toggleReason(current, key) {
  if (SOLO.includes(key)) return current.includes(key) ? [] : [key];
  const rest = current.filter((k) => !SOLO.includes(k));
  return rest.includes(key) ? rest.filter((k) => k !== key) : [...rest, key];
}

export const categoryLabel = (category) => (category === STORE ? "점포 전체" : category);
