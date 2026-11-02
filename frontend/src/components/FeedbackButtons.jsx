import { useState } from "react";
import { request } from "../api.js";

// "도움이 됐어요 / 아니에요" 평가. 한 번 누르면 끝납니다.
export default function FeedbackButtons({ kind, refId }) {
  const [sent, setSent] = useState(false);
  const [failed, setFailed] = useState(false);

  async function send(helpful) {
    setFailed(false);
    try {
      await request("/api/ai/feedback", { method: "POST", body: { kind, ref: refId, helpful } });
      setSent(true);
    } catch {
      setFailed(true);
    }
  }

  if (sent) return <p className="ai-sub">의견을 남겨 주셔서 고마워요.</p>;
  return (
    <div className="feedback">
      <span className="ai-sub">이 정리가 도움이 됐나요?</span>
      <button type="button" className="text-button" onClick={() => send(true)}>
        도움이 됐어요
      </button>
      <button type="button" className="text-button" onClick={() => send(false)}>
        아니에요
      </button>
      {failed && <span className="ai-sub">저장하지 못했어요.</span>}
    </div>
  );
}
