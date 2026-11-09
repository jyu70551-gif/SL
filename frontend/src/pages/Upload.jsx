import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, request } from "../api.js";
import UploadCalendar from "../components/UploadCalendar.jsx";
import { dateLabel, hourLabel } from "../format.js";
import { readSalesDate } from "../salesFile.js";

const HOURS = Array.from({ length: 24 }, (_, h) => h);
const HOUR_KEY = "sl.cutoffHour"; // 지난번에 고른 시각을 기억해 두었다가 처음부터 채워 줍니다 (매일 같은 시각에 올리니까요)

function lastHour() {
  try {
    const saved = localStorage.getItem(HOUR_KEY);
    return saved !== null && /^\d+$/.test(saved) && Number(saved) < 24 ? saved : "";
  } catch {
    return "";
  }
}

const rangeLabel = (iso) => iso.split("-").map(Number).join(".");

const STEPS = ["파일 선택", "내용 확인", "업로드", "반영 확인"];

const sizeText = (bytes) => (bytes < 1024 ? `${bytes}B` : bytes < 1024 * 1024 ? `${Math.round(bytes / 1024)}KB` : `${(bytes / 1024 / 1024).toFixed(1)}MB`);

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
  const [hour, setHour] = useState(lastHour);
  const [dragging, setDragging] = useState(false);
  const [done, setDone] = useState(false); // 방금 올렸는지 (홈으로 가는 버튼을 보여 줍니다)
  const [result, setResult] = useState(null); // 방금 올린 결과 { date, cutoff_hour, row_count, overwritten }
  const [fileDate, setFileDate] = useState(""); // 고른 파일 안에서 읽은 매출 날짜 (읽지 못하면 빈 값)
  const [busy, setBusy] = useState(false);
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

  useEffect(() => {
    let current = true;
    setFileDate("");
    if (file) readSalesDate(file).then((iso) => current && setFileDate(iso || ""));
    return () => {
      current = false;
    };
  }, [file]);

  function pickFile(next) {
    setFile(next);
    setDone(false);
    setResult(null);
    clearMessages();
  }

  function clearMessages() {
    setError("");
    setProblems([]);
    setConfirm(null);
  }

  async function send(content, overwrite) {
    setBusy(true);
    try {
      const saved = await request("/api/uploads", {
        method: "POST",
        body: {
          filename: file?.name || "",
          content_base64: content,
          cutoff_hour: Number(hour),
          overwrite,
        },
      });
      clearMessages();
      try {
        localStorage.setItem(HOUR_KEY, String(saved.cutoff_hour));
      } catch {
        /* 저장이 막혀 있어도 올리기는 정상입니다 */
      }
      setDone(true);
      setResult(saved);
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
      setError("파일 내용이 맞지 않아 올리지 않았어요. 아래 내용을 고친 뒤 파일을 다시 골라 주세요.");
      setProblems(e.detail.problems || []);
    } else if (code === "invalid_hour") {
      setError("집계 시각이 비어 있어요. 몇 시까지의 매출인지 골라 주세요.");
    } else if (code === "too_large") {
      setError("파일이 너무 커요(2MB 초과). 하루치 파일만 골라서 다시 올려 주세요.");
    } else if (code === "network") {
      setError("서버에 연결할 수 없어요. 인터넷 연결을 확인하고 다시 눌러 주세요.");
    } else if (code === "save_failed") {
      setError("저장하지 못했어요. 이미 올린 데이터는 그대로예요. 잠시 뒤 다시 눌러 주세요.");
    } else if (code !== "unauthorized") {
      setError("문제가 생겼어요. 잠시 뒤 다시 시도해 주세요.");
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

  const step = result ? 3 : busy || confirm ? 2 : file ? 1 : 0; // 지금 어느 단계인지 (0부터)
  const needFile = !file;
  const needHour = hour === "";
  const buttonLabel = busy ? "올리는 중…" : needFile ? "파일을 먼저 골라 주세요" : needHour ? "집계 시각을 골라 주세요" : "올리기";
  const latest = uploads && uploads.length > 0 ? uploads.reduce((a, u) => (u.date > a.date ? u : a)) : null;
  const oldest = latest ? uploads.reduce((a, u) => (u.date < a ? u.date : a), latest.date) : null;

  return (
    <section>
      <h1 className="page-title">파일 올리기</h1>

      <form className="card form" onSubmit={submit}>
        <ol className="up-steps" aria-label="올리는 순서">
          {STEPS.map((name, i) => (
            <li key={name} className={i < step ? "done" : i === step ? "current" : ""} aria-current={i === step ? "step" : undefined}>
              <span className="up-step-no" aria-hidden="true">
                {i < step ? "✓" : i + 1}
              </span>
              {name}
            </li>
          ))}
        </ol>

        <span className="form-label" id="csv-label">
          매출 파일 (CSV)
        </span>
        {/* 눌러서 고르거나 끌어다 놓습니다. 실제 파일 입력은 이 칸 안에 있어서 키보드로도 쓸 수 있어요. */}
        <label
          className={`dropzone${dragging ? " dragging" : ""}${file ? " has-file" : ""}`}
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragging(false);
            const dropped = e.dataTransfer.files?.[0];
            if (dropped) pickFile(dropped);
          }}
        >
          <input
            key={fileInputKey}
            id="csv-file"
            className="dropzone-input"
            type="file"
            accept=".csv,text/csv"
            aria-labelledby="csv-label"
            onChange={(e) => pickFile(e.target.files?.[0] || null)}
          />
          {file ? (
            <span className="dropzone-text">
              <strong>{file.name}</strong>
              <span className="muted"> · {sizeText(file.size)} · 다른 파일을 고르려면 여기를 누르세요</span>
            </span>
          ) : (
            <span className="dropzone-text">
              <strong>CSV 파일을 여기에 끌어다 놓으세요</strong>
              <span className="muted"> 또는 눌러서 고르기</span>
            </span>
          )}
        </label>
        {file && (
          <div className="up-file-row">
            {fileDate && (
              <p className="up-file-date">
                <span className="muted">파일 속 매출 날짜</span> <strong>{dateLabel(fileDate)}</strong>
              </p>
            )}
            <button
              type="button"
              className="text-button file-remove"
              onClick={() => {
                pickFile(null);
                setFileInputKey((k) => k + 1);
              }}
            >
              파일 빼기
            </button>
          </div>
        )}

        <label htmlFor="cutoff-hour">몇 시까지의 매출인가요?</label>
        <select
          id="cutoff-hour"
          value={hour}
          aria-describedby="cutoff-hint"
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
        <p id="cutoff-hint" className="muted up-hint">
          같은 시각까지의 매출끼리 비교해요.
        </p>

        <button type="submit" className="button" disabled={busy || needFile || needHour} aria-busy={busy}>
          {buttonLabel}
        </button>

        {error && (
          <div className="up-error" role="alert">
            <p className="error">{error}</p>
            {problems.length > 0 && (
              <ul className="problems">
                {problems.map((p) => (
                  <li key={p}>{p}</li>
                ))}
              </ul>
            )}
          </div>
        )}

        {result && (
          <div className="up-result" role="status">
            <p className="up-result-title">반영했어요</p>
            <dl className="up-result-list">
              <div>
                <dt>반영 날짜</dt>
                <dd>{dateLabel(result.date)}</dd>
              </div>
              <div>
                <dt>집계 시각</dt>
                <dd>{hourLabel(result.cutoff_hour)}까지</dd>
              </div>
              <div>
                <dt>올린 줄</dt>
                <dd>대분류 {result.row_count}줄</dd>
              </div>
            </dl>
            {result.overwritten && (
              <p className="up-replaced">같은 날짜의 기존 자료를 이 파일로 교체했어요. 그 날짜의 운영 상황 기록은 지워지고 새 숫자로 다시 판단해요.</p>
            )}
            <Link to="/" className="button">
              홈에서 확인하기
            </Link>
          </div>
        )}
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
            <button type="button" className="button secondary" onClick={clearMessages} disabled={busy}>
              취소
            </button>
            <button type="button" className="button" onClick={() => send(confirm.content, true)} disabled={busy}>
              덮어쓰기
            </button>
          </div>
        </div>
      )}

      <h2 className="section-title">올린 매출 기록</h2>
      {uploads === null ? (
        <p className="muted">목록을 불러오지 못했어요.</p>
      ) : !latest ? (
        <p className="muted">아직 올린 파일이 없어요.</p>
      ) : (
        <div className="card up-history">
          <div className="up-latest">
            <span className="muted">최근 반영</span>
            <strong className="up-latest-date">{dateLabel(latest.date)}</strong>
            <span>{hourLabel(latest.cutoff_hour)}까지 집계</span>
          </div>
          <p className="muted up-meta">
            전체 {uploads.length}일 · {rangeLabel(oldest)} ~ {rangeLabel(latest.date)}
          </p>
          <h3 className="up-sub">날짜별로 보기</h3>
          <UploadCalendar uploads={uploads} />
        </div>
      )}
    </section>
  );
}
