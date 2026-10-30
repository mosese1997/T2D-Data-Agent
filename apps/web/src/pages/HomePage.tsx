import { useNavigate } from 'react-router-dom';
import { useHealthStore } from '../stores/health';
import { getRecent } from '../stores/recent';
import { useWorkspaces } from '../hooks/useWorkspaces';
import { ErrorBox, Loading, relativeTime } from '../components/common/ui';
import { useI18n } from '../i18n';

export default function HomePage() {
  const navigate = useNavigate();
  const recent = getRecent();
  const health = useHealthStore((s) => s.health);
  const healthError = useHealthStore((s) => s.error);
  const reloadHealth = useHealthStore((s) => s.reload);
  const { workspaces, error: wsError } = useWorkspaces();
  const { t } = useI18n();

  const checks = health
    ? [
        { key: 'litellm', label: t('home.check.litellm'), ok: health.checks.litellm },
        { key: 'business_pg', label: t('home.check.business_pg'), ok: health.checks.business_pg },
        { key: 'state_db', label: t('home.check.state_db'), ok: health.checks.state_db },
      ]
    : [];

  return (
    <div className="page">
      <div className="home-hero">
        <h1>{t('home.heroTitle')}</h1>
        <p className="muted">{t('home.heroSub')}</p>
      </div>

      <section className="home-section">
        <h2>{t('home.recent')}</h2>
        {recent.length === 0 ? (
          <div className="muted">{t('home.recentEmpty')}</div>
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
        <h2>{t('home.workspaces')}</h2>
        {wsError && <ErrorBox message={wsError} />}
        {workspaces === null && !wsError && <Loading />}
        {workspaces && (
          <div className="card-grid">
            {workspaces.map((w) => (
              <button type="button" key={w.id} className="card dashboard-card" onClick={() => navigate(`/w/${w.id}`)}>
                <div className="dashboard-card-title">{w.name}</div>
                <div className="dashboard-card-meta">
                  <span className="muted">{w.slug}</span>
                  <span className="muted">{t('home.role', { role: w.role })}</span>
                </div>
              </button>
            ))}
          </div>
        )}
      </section>

      <section className="home-section">
        <h2>{t('home.services')}</h2>
        <div className="card checks-card">
          {healthError && <ErrorBox message={t('home.healthError', { msg: healthError })} />}
          {checks.map((c) => (
            <div key={c.key} className="check-row">
              <span className={`dot ${c.ok ? 'ok' : 'bad'}`} aria-hidden="true" />
              <span>{c.label}</span>
              <span className={`check-state ${c.ok ? 'ok-text' : 'bad-text'}`}>{c.ok ? t('home.check.ok') : t('home.check.bad')}</span>
            </div>
          ))}
          {health?.model && (
            <div className="check-row muted">
              <span>{t('common.model', { model: health.model })}</span>
            </div>
          )}
          <div>
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => void reloadHealth()}>
              {t('home.refreshStatus')}
            </button>
          </div>
        </div>
      </section>
    </div>
  );
}
