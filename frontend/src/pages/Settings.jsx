import { useEffect, useState } from "react";
import { request } from "../api.js";
import { Card } from "../components/Card.jsx";
import HolidayCard from "../components/HolidayCard.jsx";
import MarketCard from "../components/MarketCard.jsx";
import WeatherCard from "../components/WeatherCard.jsx";
import PasswordCard from "../components/PasswordCard.jsx";
import SchoolVacationCard from "../components/SchoolVacationCard.jsx";

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
      <PasswordCard />
    </section>
  );
}
