import { createContext, useCallback, useContext, useEffect, useState } from "react";
import {
  ApiError,
  clearToken,
  getToken,
  request,
  saveToken,
  setUnauthorizedHandler,
} from "./api.js";

const AuthContext = createContext(null);

export function useAuth() {
  return useContext(AuthContext);
}

// status: "checking"(확인 중) | "in"(들어옴) | "out"(비밀번호 필요) | "offline"(서버 연결 안 됨)
export function AuthProvider({ children }) {
  const [status, setStatus] = useState(getToken() ? "checking" : "out");

  const check = useCallback(async () => {
    if (!getToken()) {
      setStatus("out");
      return;
    }
    setStatus("checking");
    try {
      await request("/api/auth/me");
      setStatus("in");
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        clearToken();
        setStatus("out");
      } else {
        setStatus("offline");
      }
    }
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(() => {
      clearToken();
      setStatus("out");
    });
    check();
  }, [check]);

  const login = useCallback(async (password) => {
    const data = await request("/api/auth/login", { method: "POST", body: { password } });
    saveToken(data.token);
    setStatus("in");
  }, []);

  return (
    <AuthContext.Provider value={{ status, login, retry: check }}>{children}</AuthContext.Provider>
  );
}
