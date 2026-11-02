import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { request } from "../api.js";
import StoreCard from "../components/StoreCard.jsx";

// 처음 로그인했을 때(또는 홈의 안내에서) 점포 위치만 등록하는 화면. 방학 등 나머지는 설정 화면에서 합니다.
export default function Setup() {
  const navigate = useNavigate();
  const [hasLocation, setHasLocation] = useState(false);
  const [leaving, setLeaving] = useState(false);

  async function leave() {
    setLeaving(true);
    try {
      await request("/api/settings/setup/dismiss", { method: "POST" }); // 서버에 기억해 두면 다음 로그인에서는 다시 안 나옵니다
    } catch {
      // 저장하지 못해도 홈으로는 갈 수 있습니다. 다음에 다시 안내될 뿐입니다.
    }
    navigate("/", { replace: true });
  }

  return (
    <section>
      <div className="page-head">
        <h1 className="page-title">처음 설정</h1>
        <p className="page-meta">점포 위치를 먼저 등록해 주세요. 나머지는 설정에서 할 수 있어요.</p>
      </div>

      <StoreCard locationOnly onChange={(store) => setHasLocation(store.latitude != null)} />

      <div className="button-row setup-actions">
        {hasLocation && (
          <button type="button" className="button" onClick={leave} disabled={leaving}>
            완료
          </button>
        )}
        <button type="button" className="button secondary" onClick={leave} disabled={leaving}>
          {hasLocation ? "나중에 하기" : "나중에 하기 (홈으로)"}
        </button>
      </div>
      <p className="card-note">
        {hasLocation
          ? "장날과 근처 학교 방학은 설정 화면에서 입력할 수 있어요."
          : "건너뛰어도 매출 확인은 그대로 쓸 수 있어요. 설정 화면에서 언제든 등록할 수 있어요."}
      </p>
    </section>
  );
}
