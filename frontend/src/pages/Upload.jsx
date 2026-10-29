import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, request } from "../api.js";
import { dateLabel, hourLabel } from "../format.js";

const HOURS = Array.from({ length: 24 }, (_, h) => h);

async function fileToBase64(file) {
  const bytes = new Uint8Array(await file.arrayBuffer());
  let binary = "";
  const chunk = 0x8000;
  for (let i = 0; i < bytes.length; i += chunk) {
    binary += String.fromCharCode.apply(null, bytes.subarray(i, i + chunk));
  }
  return btoa(binary);
}

export default function Upload() {
  const [file, setFile] = useState(null);
  const [hour, setHour] = useState("");
  const [busy, setBusy] = useState(false);
  const [success, setSuccess] = useState("");
  const [error, setError] = useState("");
  const [problems, setProblems] = useState([]);
  const [confirm, setConfirm] = useState(null); // { date, cutoffHour, content }
  const [uploads, setUploads] = useState(null);
  const [fileInputKey, setFileInputKey] = useState(0);
  const lastContent = useRef("");

  const loadUploads = useCallback(async () => {
    try {
      setUploads(await request("/api/uploads"));
    } catch {
      setUploads(null);
    }
  }, []);

  useEffect(() => {
    loadUploads();
  }, [loadUploads]);

  function clearMessages() {
    setSuccess("");
    setError("");
    setProblems([]);
    setConfirm(null);
  }

  async function send(content, overwrite) {
    setBusy(true);
    try {
      const result = await request("/api/uploads", {
        method: "POST",
        body: {
          filename: file?.name || "",
          content_base64: content,
          cutoff_hour: Number(hour),
          overwrite,
        },
      });
      clearMessages();
      setSuccess(
        `${dateLabel(result.date)} 매출을 ${result.overwritten ? "덮어써서 " : ""}올렸어요. ` +
          `(${hourLabel(result.cutoff_hour)}까지, 대분류 ${result.row_count}줄)`,
      );
      setFile(null);
      setFileInputKey((k) => k + 1);
      await loadUploads();
    } catch (e) {
      handleError(e, content);
    } finally {
      setBusy(false);
    }
  }

  function handleError(e, content) {
    clearMessages();
    if (!(e instanceof ApiError)) {
      setError("문제가 생겼어요. 잠시 후 다시 시도해 주세요.");
      return;
    }
    const code = e.detail.code;
    if (code === "date_exists") {
      setConfirm({ date: e.detail.date, cutoffHour: e.detail.cutoff_hour, content });
    } else if (code === "invalid_file") {
      setError("이 파일은 올릴 수 없어요. 아래 내용을 확인해 주세요.");
      setProblems(e.detail.problems || []);
    } else if (code === "invalid_hour") {
      setError("몇 시까지의 매출인지 선택해 주세요.");
    } else if (code === "too_large") {
      setError("파일이 너무 커요. (2MB 이하만 올릴 수 있어요)");
    } else if (code === "network") {
      setError("서버에 연결할 수 없어요.");
    } else if (code === "save_failed") {
      setError("저장하지 못했어요. 이미 올린 데이터는 그대로예요. 잠시 후 다시 시도해 주세요.");
    } else if (code !== "unauthorized") {
      setError("문제가 생겼어요. 잠시 후 다시 시도해 주세요.");
    }
  }

  async function submit(event) {
    event.preventDefault();
    if (busy) return;
    clearMessages();
    if (!file) {
      setError("올릴 CSV 파일을 골라 주세요.");
      return;
    }
    if (hour === "") {
      setError("몇 시까지의 매출인지 선택해 주세요.");
      return;
    }
    const content = await fileToBase64(file);
    lastContent.current = content;
    await send(content, false);
  }

  return (
    <section>
      <h1 className="page-title">파일 올리기</h1>

      <form className="card form" onSubmit={submit}>
        <label htmlFor="csv-file">매출 파일 (CSV)</label>
        <input
          key={fileInputKey}
          id="csv-file"
          type="file"
          accept=".csv,text/csv"
          onChange={(e) => {
            setFile(e.target.files?.[0] || null);
            clearMessages();
          }}
        />

        <label htmlFor="cutoff-hour">몇 시까지의 매출인가요?</label>
        <select
          id="cutoff-hour"
          value={hour}
          onChange={(e) => {
            setHour(e.target.value);
            setError("");
          }}
        >
          <option value="">시각을 선택하세요</option>
          {HOURS.map((h) => (
            <option key={h} value={h}>
              {hourLabel(h)}
            </option>
          ))}
        </select>

        <button type="submit" className="button" disabled={busy}>
          {busy ? "올리는 중…" : "올리기"}
        </button>
      </form>

      {confirm && (
        <div className="card confirm" role="alertdialog" aria-labelledby="confirm-title">
          <p id="confirm-title" className="confirm-title">
            {dateLabel(confirm.date)} 데이터가 이미 있어요.
          </p>
          <p className="muted">
            덮어쓰면 그 날짜의 &lsquo;운영 상황 기록&rsquo;이 지워지고, 새 숫자로 판매 변화가 큰 날을
            다시 판단해요. 지금 저장된 데이터는 {hourLabel(confirm.cutoffHour)}까지의 매출이에요.
          </p>
          <div className="button-row">
            <button
              type="button"
              className="button secondary"
              onClick={clearMessages}
              disabled={busy}
            >
              취소
            </button>
            <button
              type="button"
              className="button"
              onClick={() => send(confirm.content, true)}
              disabled={busy}
            >
              덮어쓰기
            </button>
          </div>
        </div>
      )}

      {success && (
        <p className="success" role="status">
          {success}
        </p>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {problems.length > 0 && (
        <ul className="problems">
          {problems.map((p) => (
            <li key={p}>{p}</li>
          ))}
        </ul>
      )}

      <h2 className="section-title">올려 둔 날짜</h2>
      {uploads === null ? (
        <p className="muted">목록을 불러오지 못했어요.</p>
      ) : uploads.length === 0 ? (
        <p className="muted">아직 올린 파일이 없어요.</p>
      ) : (
        <ul className="upload-list">
          {uploads.map((u) => (
            <li key={u.date}>
              <span>{dateLabel(u.date)}</span>
              <span className="muted">{hourLabel(u.cutoff_hour)}까지</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
