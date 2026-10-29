import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { errorMessage } from '../api/error';
import { login, useAuthStore } from '../stores/auth';
import { useHealthStore } from '../stores/health';
import { ErrorBox } from '../components/common/ui';

const DEMO_ACCOUNTS = [
  { username: 'admin', password: 'admin-demo-2026', label: '管理员 admin' },
  { username: 'analyst_a', password: 'analyst-demo-2026', label: '分析师 analyst_a' },
  { username: 'analyst_b', password: 'analyst-demo-2026', label: '分析师 analyst_b' },
  { username: 'viewer_b', password: 'viewer-demo-2026', label: '查看者 viewer_b' },
  { username: 'viewer_c', password: 'viewer-demo-2026', label: '查看者 viewer_c' },
  { username: 'ops', password: 'ops-demo-2026', label: '运维 ops' },
];

export default function LoginPage() {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();
  const token = useAuthStore((s) => s.token);
  const brand = useHealthStore((s) => s.health?.brand ?? 't2d');
  const demoMode = useHealthStore((s) => s.health?.demo_mode === true);

  useEffect(() => {
    if (token) navigate('/', { replace: true });
  }, [token, navigate]);

  const from = (location.state as { from?: string } | null)?.from ?? '/';

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await login(username.trim(), password);
      navigate(from, { replace: true });
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login-page">
      <div className="login-card">
        <div className="login-brand">{brand}</div>
        <div className="login-sub">Agentic Talk to Data</div>
        <form onSubmit={submit}>
          <label className="field">
            <span>用户名</span>
            <input
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoFocus
              autoComplete="username"
            />
          </label>
          <label className="field">
            <span>密码</span>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
            />
          </label>
          {error && <ErrorBox message={error} />}
          <button className="btn btn-primary btn-block" type="submit" disabled={busy || !username.trim() || !password}>
            {busy ? '登录中…' : '登录'}
          </button>
        </form>
        <div className="login-demo">
          <div className="login-demo-title">演示账号（点击一键填入）</div>
          <div className="login-demo-grid">
            {DEMO_ACCOUNTS.map((a) => (
              <button
                type="button"
                key={a.username}
                className="btn btn-ghost btn-sm"
                onClick={() => {
                  setUsername(a.username);
                  setPassword(a.password);
                }}
              >
                {a.label}
              </button>
            ))}
          </div>
          <div className="login-env-note muted">HTTP 演示环境{demoMode ? ' · 当前为演示数据模式' : ''}</div>
        </div>
      </div>
    </div>
  );
}
