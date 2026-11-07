import type { ReactNode } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "./useAuth";
import { Layout } from "./components/Layout";
import { AnomalyPage } from "./pages/AnomalyPage";
import { GlobePage } from "./pages/GlobePage";
import { DashboardPage } from "./pages/DashboardPage";
import { LoginPage } from "./pages/LoginPage";
import { SignupPage } from "./pages/SignupPage";
import { UploadPage } from "./pages/UploadPage";

export default function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/signup" element={<SignupPage />} />
        <Route path="/" element={<RequireAuth><DashboardPage /></RequireAuth>} />
        <Route path="/upload" element={<RequireAuth><UploadPage /></RequireAuth>} />
        <Route path="/anomalies/:anomalyId" element={<RequireAuth><AnomalyPage /></RequireAuth>} />
        <Route path="/anomalies/:anomalyId/globe" element={<RequireAuth><GlobePage /></RequireAuth>} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Layout>
  );
}

function RequireAuth({ children }: { children: ReactNode }) {
  const { ready, session } = useAuth();
  if (!ready) {
    return <p className="text-sm text-slate-400">Checking your session…</p>;
  }
  if (!session) {
    return <Navigate to="/login" replace />;
  }
  return children;
}
