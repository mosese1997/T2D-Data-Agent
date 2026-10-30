import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { api } from '../api/client';
import { errorMessage } from '../api/error';
import type { DashboardSummary } from '../api/types';
import { useWorkspaces } from '../hooks/useWorkspaces';
import { ErrorBox, Loading, StatusBadge, formatDateTime } from '../components/common/ui';
import { useI18n } from '../i18n';

export default function WorkspacePage() {
  const { workspaceId } = useParams();
  const wid = Number(workspaceId);
  const navigate = useNavigate();
  const [dashboards, setDashboards] = useState<DashboardSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const { workspaces } = useWorkspaces();
  const ws = workspaces?.find((w) => w.id === wid) ?? null;
  const { t } = useI18n();

  useEffect(() => {
    let alive = true;
    setDashboards(null);
    setError(null);
    api
      .get<DashboardSummary[]>(`/api/workspaces/${wid}/dashboards`)
      .then((list) => {
        if (alive) setDashboards(list);
      })
      .catch((e) => {
        if (alive) setError(errorMessage(e));
      });
    return () => {
      alive = false;
    };
  }, [wid]);

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>{ws?.name ?? t('ws.fallbackName', { id: wid })}</h1>
          <p className="muted">{ws ? t('ws.roleLine', { slug: ws.slug, role: ws.role }) : ''}</p>
        </div>
        <button type="button" className="btn btn-primary" onClick={() => navigate(`/w/${wid}/new`)}>
          {t('ws.newDashboard')}
        </button>
      </div>

      {error && <ErrorBox message={error} />}
      {dashboards === null && !error && <Loading />}
      {dashboards !== null && (
        <div className="card-grid">
          {dashboards.map((d) => (
            <button
              type="button"
              key={d.id}
              className="card dashboard-card"
              onClick={() => navigate(`/w/${wid}/d/${d.id}`)}
            >
              <div className="dashboard-card-title">{d.title}</div>
              <div className="dashboard-card-meta">
                <StatusBadge status={d.status} />
                <span className="muted">{t('ws.updatedAt', { time: formatDateTime(d.updated_at) })}</span>
              </div>
            </button>
          ))}
          {dashboards.length === 0 && (
            <div className="muted">{t('ws.empty')}</div>
          )}
        </div>
      )}
    </div>
  );
}
