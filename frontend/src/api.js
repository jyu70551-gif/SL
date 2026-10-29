// 서버와 말하는 곳. 로그인 통행증(토큰)은 이 폰(브라우저)에 보관합니다.
// 앱으로 감싸더라도 같은 방식으로 쓸 수 있도록 쿠키가 아닌 헤더 방식입니다.
const BASE_URL = import.meta.env.VITE_API_BASE_URL || "";
const TOKEN_KEY = "sl_token";

export function getToken() {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function saveToken(token) {
  try {
    localStorage.setItem(TOKEN_KEY, token);
  } catch {
    // 저장할 수 없는 브라우저에서는 이번 접속에서만 로그인이 유지됩니다.
  }
}

export function clearToken() {
  try {
    localStorage.removeItem(TOKEN_KEY);
  } catch {
    // 무시
  }
}

let onUnauthorized = () => {};
export function setUnauthorizedHandler(fn) {
  onUnauthorized = fn;
}

export class ApiError extends Error {
  constructor(status, detail) {
    super(detail?.code || `http_${status}`);
    this.status = status;
    this.detail = detail || {};
  }
}

export async function request(path, { method = "GET", body } = {}) {
  const headers = {};
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";

  let res;
  try {
    res = await fetch(`${BASE_URL}${path}`, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiError(0, { code: "network" });
  }

  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    if (res.status === 401 && token && data?.detail?.code === "unauthorized") {
      onUnauthorized();
    }
    throw new ApiError(res.status, data?.detail);
  }
  return data;
}
