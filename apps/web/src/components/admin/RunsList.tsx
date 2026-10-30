import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../../api/client';
import { errorDetail } from '../../api/error';
import type { AdminRun } from '../../api/types';
import { useI18n } from '../../i18n';
import { ErrorBox, Loading, RunStatusBadge, formatDateTime } from '../common/ui';

/** 任务运行列表（GET /api/admin/runs，仅管理员）。点击行进入 Trace 详情。 */
export default function RunsList({ limit = 50 }: { limit?: number }) {
  const navigate = useNavigate();
  const [runs, setRuns] = useState<AdminRun[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const { t } = useI18n();

  const load = useCallback(() => {
    let alive = true;
    setRuns(null);
    setError(null);
    api
      .get<AdminRun[]>(`/api/admin/runs?limit=${limit}`)
      .then((r) => {
        if (alive) setRuns(r);
      })
      .catch((e) => {
        if (alive) setError(errorDetail(e));
      });
    return () => {
      alive = false;
    };
  }, [limit]);

  useEffect(() => load(), [load]);

  return (
    <div>
      <div className="runs-list-head">
        <span className="muted">{t('runs.hint', { limit })}</span>
        <button type="button" className="btn btn-ghost btn-sm" onClick={() => load()}>
          {t('common.refresh')}
        </button>
      </div>
      {error && <ErrorBox message={error} />}
      {runs === null && !error && <Loading label={t('runs.loading')} />}
      {runs !== null && (
        <div className="card table-scroll">
          <table className="data-table row-click">
            <thead>
              <tr>
                <th>{t('runs.th.task')}</th>
                <th>{t('runs.th.type')}</th>
                <th>{t('runs.th.status')}</th>
                <th>{t('runs.th.createdAt')}</th>
                <th>{t('runs.th.error')}</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((r) => (
                <tr key={r.task_id} onClick={() => navigate(`/admin/runs/${r.task_id}`)}>
                  <td>#{r.task_id}</td>
                  <td>{r.type ?? '—'}</td>
                  <td>
                    <RunStatusBadge status={r.status} />
                  </td>
                  <td>{formatDateTime(r.created_at)}</td>
                  <td className="cell-error" title={r.error ?? undefined}>
                    {r.error ?? '—'}
                  </td>
                </tr>
              ))}
              {runs.length === 0 && (
                <tr>
                  <td colSpan={5} className="muted">
                    {t('runs.empty')}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
