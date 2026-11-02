import { useEffect, useState } from "react";
import { request } from "../api.js";
import { Card } from "../components/Card.jsx";
import HolidayCard from "../components/HolidayCard.jsx";
import MarketCard from "../components/MarketCard.jsx";
import WeatherCard from "../components/WeatherCard.jsx";
import PasswordCard from "../components/PasswordCard.jsx";
import SchoolVacationCard from "../components/SchoolVacationCard.jsx";

const STATE_TEXT = {
  ready: "켜져 있어요",
  off: "꺼져 있어요 (AI_ENABLED=false)",
  no_key: "키가 아직 없어요",
  limit: "이번 달 사용 한도에 도달했어요",
  degraded: "연결이 불안정해서 잠시 쉬고 있어요",
  key_invalid: "키가 올바르지 않아요",
};

const ERROR_TEXT = {
  auth: "키가 올바르지 않거나 권한이 없어요.",
  model: "모델 이름을 찾을 수 없어요. OPENAI_MODEL을 확인하거나 비워 두세요.",
  no_model: "이 키로 쓸 수 있는 모델을 찾지 못했어요. OPENAI_MODEL에 모델 이름을 적어 주세요.",
  rate_limit: "OpenAI 사용 한도나 잔액에 걸렸어요.",
  timeout: "응답이 늦어서 중단했어요.",
  connection: "OpenAI에 연결하지 못했어요.",
  server: "OpenAI 서버에 문제가 있어요.",
  invalid: "응답 형식이 맞지 않았어요.",
  guard: "AI 응답이 규칙을 지키지 못해 쓰지 않았어요.",
};

function AiStatus() {
  const [status, setStatus] = useState(null);
  const [metrics, setMetrics] = useState(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let alive = true;
    Promise.all([request("/api/ai/status"), request("/api/ai/metrics")])
      .then(([s, m]) => {
        if (alive) {
          setStatus(s);
          setMetrics(m);
        }
      })
      .catch(() => alive && setFailed(true));
    return () => {
      alive = false;
    };
  }, []);

  if (failed) {
    return (
      <Card title="AI 점검">
        <p className="card-note">상태를 불러오지 못했어요.</p>
      </Card>
    );
  }
  if (!status) {
    return (
      <Card title="AI 점검">
        <p className="card-note">불러오는 중…</p>
      </Card>
    );
  }

  const rated = metrics.feedback.helpful + metrics.feedback.not_helpful;
  const noteTotal = metrics.notes.form + metrics.notes.ai;
  return (
    <Card title="AI 점검">
      <dl className="stat-list">
        <div>
          <dt>상태</dt>
          <dd>{STATE_TEXT[status.state] ?? status.state}</dd>
        </div>
        <div>
          <dt>이번 달 사용</dt>
          <dd>
            {status.month_used} / {status.month_limit}번
          </dd>
        </div>
        <div>
          <dt>모델</dt>
          <dd>{status.model}</dd>
        </div>
        {rated > 0 && (
          <div>
            <dt>도움이 됐다는 평가</dt>
            <dd>
              {metrics.feedback.helpful} / {rated}
            </dd>
          </div>
        )}
        {noteTotal > 0 && (
          <div>
            <dt>AI로 정리한 기록</dt>
            <dd>
              {metrics.notes.ai} / {noteTotal}
              {metrics.notes.ai > 0 && ` (고쳐서 저장 ${metrics.notes.ai_edited})`}
            </dd>
          </div>
        )}
      </dl>
      {status.last_error && <p className="card-note">최근 문제: {ERROR_TEXT[status.last_error] ?? status.last_error}</p>}
      {status.problems.map((problem) => (
        <p key={problem} className="card-note">
          {problem}
        </p>
      ))}
      {status.state === "no_key" && (
        <p className="card-note">
          OpenAI 키를 쓰려면 <strong>backend/.env</strong> 파일에 <strong>OPENAI_API_KEY=키</strong> 한 줄을 넣으세요. 서버를 다시 켜지
          않아도 반영돼요. 키는 채팅이나 문서에 적지 마세요.
        </p>
      )}
      <p className="card-note">
        대분류 이름, 날짜, 금액, 점주님이 &lsquo;한마디로 남기기&rsquo;에 쓴 글이 정리를 위해 OpenAI로 전송돼요. AI는 원인을 단정하지 않고
        확인할 일을 정리해 줘요.
      </p>
    </Card>
  );
}

function Sensitivity() {
  const [data, setData] = useState(null);
  const [failed, setFailed] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let alive = true;
    request("/api/settings/sensitivity")
      .then((d) => alive && setData(d))
      .catch(() => alive && setFailed(true));
    return () => {
      alive = false;
    };
  }, []);

  async function choose(level) {
    if (saving || data?.level === level) return;
    setSaving(true);
    setFailed(false);
    try {
      setData(await request("/api/settings/sensitivity", { method: "POST", body: { level } }));
    } catch {
      setFailed(true);
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card title="알림 민감도">
      {!data && !failed && <p className="card-note">불러오는 중…</p>}
      {data && (
        <div className="sensitivity" role="radiogroup" aria-label="알림 민감도">
          {data.options.map((option) => (
            <label key={option.level} className={`sensitivity-option${data.level === option.level ? " selected" : ""}`}>
              <input
                type="radio"
                name="sensitivity"
                value={option.level}
                checked={data.level === option.level}
                disabled={saving}
                onChange={() => choose(option.level)}
              />
              <span>
                <strong>{option.label}</strong>
                <span className="sensitivity-text">{option.text}</span>
              </span>
            </label>
          ))}
        </div>
      )}
      {failed && <p className="card-note">설정을 불러오거나 저장하지 못했어요. 잠시 뒤 다시 시도해 주세요.</p>}
      <p className="card-note">
        ‘확인할 사항’에 얼마나 잘 올릴지 정해요. 높을수록 작은 변화도 일찍 알려 주지만 알림이 늘어나요. 알림이 너무 많으면 낮추고, 놓치는 것이
        걱정되면 높여 보세요.
      </p>
    </Card>
  );
}

export default function Settings() {
  return (
    <section>
      <h1 className="page-title">설정</h1>
      <SchoolVacationCard />
      <MarketCard />
      <HolidayCard />
      <WeatherCard />
      <Sensitivity />
      <AiStatus />
      <PasswordCard />
    </section>
  );
}
