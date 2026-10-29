import { Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "./auth.jsx";
import Layout from "./components/Layout.jsx";
import Home from "./pages/Home.jsx";
import Login from "./pages/Login.jsx";
import Settings from "./pages/Settings.jsx";
import Upload from "./pages/Upload.jsx";

export default function App() {
  const { status, retry } = useAuth();

  if (status === "checking") {
    return <p className="center-note">확인하는 중…</p>;
  }

  if (status === "offline") {
    return (
      <div className="center-note">
        <p>서버에 연결할 수 없어요.</p>
        <button type="button" className="button" onClick={retry}>
          다시 시도
        </button>
      </div>
    );
  }

  if (status === "out") {
    return <Login />;
  }

  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Home />} />
        <Route path="upload" element={<Upload />} />
        <Route path="settings" element={<Settings />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
