import { useNavigate } from 'react-router-dom';
import { useHealthStore } from '../stores/health';
import { getRecent } from '../stores/recent';
import { useWorkspaces } from '../hooks/useWorkspaces';
import { ErrorBox, Loading, relativeTime } from '../components/common/ui';

export default function HomePage() {
  const navigate = useNavigate();
  const recent = getRecent();
  const health = useHealthStore((s) => s.health);
  const healthError = useHealthStore((s) => s.error);
  const reloadHealth = useHealthStore((s) => s.reload);
  const { workspaces, error: wsError } = useWorkspaces();

  const checks = health
    ? [
        { key: 'litellm', label: 'LLM 网关（LiteLLM）', ok: health.checks.litellm },
        { key: 'business_pg', label: '业务数据库（PostgreSQL）', ok: health.checks.business_pg },
        { key: 'state_db', label: '状态数据库', ok: health.checks.state_db },
      ]
    : [];

  return (
    <div className="page">
      <div className="home-hero">
        <h1>欢迎使用 t2d</h1>
        <p className="muted">Agentic Talk to Data —— 用自然语言对话，让 Agent 查询数据、搭建并修改看板。</p>
      </div>

      <section className="home-section">
        <h2>最近访问的看板</h2>
        {recent.length === 0 ? (
          <div className="muted">暂无记录。从下方工作空间打开一个看板开始。</div>
        ) : (
          <div className="card-grid">
            {recent.map((r) => (
              <button
                type="button"
                key={r.dashboardId}
                className="card dashboard-card"
                onClick={() => navigate(`/w/${r.workspaceId}/d/${r.dashboardId}`)}
              >
                <div className="dashboard-card-title">{r.title}</div>
                <div className="dashboard-card-meta">
                  <span>{r.workspaceName}</span>
                  <span className="muted">{relativeTime(r.at)}</span>
                </div>
              </button>
            ))}
          </div>
        )}
      </section>

      <section className="home-section">
        <h2>工作空间</h2>
        {wsError && <ErrorBox message={wsError} />}
        {workspaces === null && !wsError && <Loading />}
        {workspaces && (
          <div className="card-grid">
            {workspaces.map((w) => (
              <button type="button" key={w.id} className="card dashboard-card" onClick={() => navigate(`/w/${w.id}`)}>
                <div className="dashboard-card-title">{w.name}</div>
                <div className="dashboard-card-meta">
                  <span className="muted">{w.slug}</span>
                  <span className="muted">角色：{w.role}</span>
                </div>
              </button>
            ))}
          </div>
        )}
      </section>

      <section className="home-section">
        <h2>服务连接状态</h2>
        <div className="card checks-card">
          {healthError && <ErrorBox message={`无法获取健康状态：${healthError}`} />}
          {checks.map((c) => (
            <div key={c.key} className="check-row">
              <span className={`dot ${c.ok ? 'ok' : 'bad'}`} aria-hidden="true" />
              <span>{c.label}</span>
              <span className={`check-state ${c.ok ? 'ok-text' : 'bad-text'}`}>{c.ok ? '正常' : '异常'}</span>
            </div>
          ))}
          {health?.model && (
            <div className="check-row muted">
              <span>模型：{health.model}</span>
            </div>
          )}
          <div>
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => void reloadHealth()}>
              刷新状态
            </button>
          </div>
        </div>
      </section>
    </div>
  );
}
