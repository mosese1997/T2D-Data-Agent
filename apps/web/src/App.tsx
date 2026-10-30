import { useEffect } from 'react';
import { Navigate, Outlet, Route, Routes, useLocation } from 'react-router-dom';
import { api } from './api/client';
import type { User } from './api/types';
import { useAuthStore } from './stores/auth';
import { useHealthStore } from './stores/health';
import { useI18n } from './i18n';
import TopBar from './components/common/TopBar';
import DemoBanner from './components/common/DemoBanner';
import { Loading } from './components/common/ui';
import LoginPage from './pages/LoginPage';
import HomePage from './pages/HomePage';
import WorkspacePage from './pages/WorkspacePage';
import StudioPage from './pages/StudioPage';
import SourcesPage from './pages/SourcesPage';
import RequestsPage from './pages/RequestsPage';
import ActivityPage from './pages/ActivityPage';
import WikiPage from './pages/WikiPage';
import AdminPage from './pages/AdminPage';
import AdminRunTracePage from './pages/AdminRunTracePage';

function RequireAuth() {
  const { token, ready } = useAuthStore();
  const location = useLocation();
  const { t } = useI18n();
  if (!ready) {
    return (
      <div className="page-center">
        <Loading label={t('app.restoringSession')} />
      </div>
    );
  }
  if (!token) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }
  return <Outlet />;
}

function AppShell() {
  return (
    <div className="app-shell">
      <TopBar />
      <DemoBanner />
      <main className="app-main">
        <Outlet />
      </main>
    </div>
  );
}

export default function App() {
  const token = useAuthStore((s) => s.token);
  const markReady = useAuthStore((s) => s.markReady);
  const setUser = useAuthStore((s) => s.setUser);
  const reloadHealth = useHealthStore((s) => s.reload);

  useEffect(() => {
    void reloadHealth();
  }, [reloadHealth]);

  // 启动时校验本地保存的 token
  useEffect(() => {
    if (!token) {
      markReady();
      return;
    }
    let alive = true;
    api
      .get<User>('/api/auth/me')
      .then((user) => {
        if (alive) setUser(user);
      })
      .catch(() => {
        // 401 已由 api client 统一处理（登出）；其他错误保留会话
      })
      .finally(() => {
        if (alive) markReady();
      });
    return () => {
      alive = false;
    };
  }, [token, markReady, setUser]);

  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<RequireAuth />}>
        <Route element={<AppShell />}>
          <Route path="/" element={<HomePage />} />
          <Route path="/w/:workspaceId" element={<WorkspacePage />} />
          <Route path="/w/:workspaceId/new" element={<StudioPage />} />
          <Route path="/w/:workspaceId/d/:dashboardId" element={<StudioPage />} />
          <Route path="/w/:workspaceId/sources" element={<SourcesPage />} />
          <Route path="/requests" element={<RequestsPage />} />
          <Route path="/activity" element={<ActivityPage />} />
          <Route path="/wiki" element={<WikiPage />} />
          <Route path="/admin" element={<AdminPage />} />
          <Route path="/admin/runs/:taskId" element={<AdminRunTracePage />} />
        </Route>
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
