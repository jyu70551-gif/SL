import { useEffect, useState } from "react";
import { request } from "../api.js";

// 이전에 같은 분류에서 비슷한 변화가 있었을 때 점주가 남긴 기록. AI가 아니라 저장된 기록을 날짜로 찾아 보여줍니다.
// "이번에도 같은 이유"라고 단정하지 않습니다.
export default function SimilarRecords({ category, date }) {
  const [items, setItems] = useState([]);

  useEffect(() => {
    let alive = true;
    request(`/api/ai/similar?category=${encodeURIComponent(category)}&date=${date}`)
      .then((body) => alive && setItems(body.items ?? []))
      .catch(() => alive && setItems([]));
    return () => {
      alive = false;
    };
  }, [category, date]);

  if (items.length === 0) return null;
  return (
    <div className="similar">
      <p className="similar-title">이전 기록</p>
      <ul className="basis-items">
        {items.map((item) => (
          <li key={item.date}>{item.text}</li>
        ))}
      </ul>
    </div>
  );
}
