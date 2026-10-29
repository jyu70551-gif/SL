export function Card({ title, chip, chipTone = "", footer, keyMark = false, children }) {
  return (
    <section className="card">
      <div className="card-head">
        <h2 className={keyMark ? "card-title key" : "card-title"}>{title}</h2>
        {chip && <span className={`chip ${chipTone}`}>{chip}</span>}
      </div>
      {children}
      {footer && <p className="card-foot">{footer}</p>}
    </section>
  );
}

// 데이터가 더 쌓여야 보여줄 수 있는 부분의 안내. 오류가 아니라 정상 상태입니다.
export function NeedMore({ comparison, weekday }) {
  const { weeks_used: used, min_days: min, needed_more: more, excluded_other_hour: excluded } = comparison;
  return (
    <div className="need-more">
      <span>
        <strong>데이터가 더 필요해요.</strong> 같은 {weekday}요일, 같은 시각까지의 매출이 {min}번 쌓이면 평소와
        비교해 드려요. ({used}/{min}, {more}번 더 필요)
      </span>
      <div className="progress-dots" aria-hidden="true">
        {Array.from({ length: min }, (_, i) => (
          <span key={i} className={i < used ? "on" : ""} />
        ))}
      </div>
      {excluded > 0 && (
        <span>마감 시각이 달라서 비교에서 뺀 같은 요일이 {excluded}번 있어요.</span>
      )}
    </div>
  );
}
