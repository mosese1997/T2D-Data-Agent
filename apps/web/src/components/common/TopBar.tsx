import { useEffect, useMemo, useRef, useState } from 'react';
import { NavLink, useLocation, useNavigate } from 'react-router-dom';
import { useAuthStore } from '../../stores/auth';
import { useHealthStore } from '../../stores/health';
import { useWorkspaces } from '../../hooks/useWorkspaces';
import { useIsAdmin } from '../../hooks/useIsAdmin';

export default function TopBar() {
  const navigate = useNavigate();
  const location = useLocation();
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
  const brand = useHealthStore((s) => s.health?.brand ?? 't2d');
  const { workspaces } = useWorkspaces();
  const isAdmin = useIsAdmin();

  const [wsMenuOpen, setWsMenuOpen] = useState(false);
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const wsRef = useRef<HTMLDivElement>(null);
  const userRef = useRef<HTMLDivElement>(null);

  const currentWsId = useMemo(() => {
    const m = location.pathname.match(/^\/w\/(\d+)/);
    return m ? Number(m[1]) : null;
  }, [location.pathname]);
  const currentWs = workspaces?.find((w) => w.id === currentWsId) ?? null;

  useEffect(() => {
    if (!wsMenuOpen && !userMenuOpen) return;
    const onDocClick = (e: MouseEvent) => {
      const target = e.target as Node;
      if (wsMenuOpen && wsRef.current && !wsRef.current.contains(target)) setWsMenuOpen(false);
      if (userMenuOpen && userRef.current && !userRef.current.contains(target)) setUserMenuOpen(false);
    };
    document.addEventListener('mousedown', onDocClick);
    return () => document.removeEventListener('mousedown', onDocClick);
  }, [wsMenuOpen, userMenuOpen]);

  const handleLogout = () => {
    logout();
    navigate('/login', { replace: true });
  };

  return (
    <header className="topbar">
      <button type="button" className="brand" onClick={() => navigate('/')} title="回到首页">
        <span className="brand-mark">{brand}</span>
        <span className="brand-sub">Agentic Talk to Data</span>
      </button>

      <div className="topbar-center">
        <div className="menu-root" ref={wsRef}>
          <button type="button" className="menu-trigger" onClick={() => setWsMenuOpen((v) => !v)}>
            {currentWs ? currentWs.name : '工作空间'}
            <span className="caret" aria-hidden="true">▾</span>
          </button>
          {wsMenuOpen && (
            <div className="menu-pop">
              {workspaces === null && <div className="menu-item static muted">加载中…</div>}
              {workspaces?.map((w) => (
                <button
                  key={w.id}
                  type="button"
                  className={`menu-item ${w.id === currentWsId ? 'active' : ''}`}
                  onClick={() => {
                    setWsMenuOpen(false);
                    navigate(`/w/${w.id}`);
                  }}
                >
                  <span>{w.name}</span>
                  <span className="menu-item-tag">{w.role}</span>
                </button>
              ))}
            </div>
          )}
        </div>
        {currentWsId !== null && (
          <nav className="topbar-tabs">
            <NavLink to={`/w/${currentWsId}`} end className={({ isActive }) => `tab ${isActive ? 'active' : ''}`}>
              看板
            </NavLink>
            <NavLink to={`/w/${currentWsId}/sources`} className={({ isActive }) => `tab ${isActive ? 'active' : ''}`}>
              数据源
            </NavLink>
          </nav>
        )}
        <nav className="topbar-tabs topbar-global" aria-label="全局导航">
          <NavLink to="/requests" className={({ isActive }) => `tab ${isActive ? 'active' : ''}`}>
            审批
          </NavLink>
          <NavLink to="/activity" className={({ isActive }) => `tab ${isActive ? 'active' : ''}`}>
            活动
          </NavLink>
          <NavLink to="/wiki" className={({ isActive }) => `tab ${isActive ? 'active' : ''}`}>
            Wiki
          </NavLink>
          {isAdmin === true && (
            <NavLink
              to="/admin"
              className={({ isActive }) => `tab ${isActive ? 'active' : ''}`}
            >
              管理台
            </NavLink>
          )}
        </nav>
      </div>

      <div className="topbar-right">
        <div className="menu-root" ref={userRef}>
          <button type="button" className="menu-trigger" onClick={() => setUserMenuOpen((v) => !v)}>
            {user?.display_name || user?.username || '未登录'}
            <span className="caret" aria-hidden="true">▾</span>
          </button>
          {userMenuOpen && (
            <div className="menu-pop menu-pop-right">
              <div className="menu-item static">@{user?.username ?? '—'}</div>
              <button type="button" className="menu-item" onClick={handleLogout}>
                退出登录
              </button>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
