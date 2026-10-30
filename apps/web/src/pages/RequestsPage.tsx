import { useCallback, useEffect, useState } from 'react';
import { api } from '../api/client';
import { errorDetail } from '../api/error';
import type { ApprovalRequest } from '../api/types';
import { useI18n } from '../i18n';
import { ErrorBox, Loading, formatDateTime } from '../components/common/ui';
import { useIsAdmin } from '../hooks/useIsAdmin';

/**
 * 发布审批（任务书 §13）：待审批的看板发布请求。
 * 后端只返回「当前用户是目标空间 admin」的请求；非 admin 在前端直接给出权限空态。
 */
export default function RequestsPage() {
  const isAdmin = useIsAdmin();
  const [requests, setRequests] = useState<ApprovalRequest[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [actingId, setActingId] = useState<number | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionDone, setActionDone] = useState<string | null>(null);
  const { t } = useI18n();

  const load = useCallback(() => {
    let alive = true;
    setRequests(null);
    setError(null);
    api
      .get<ApprovalRequest[]>('/api/requests')
      .then((r) => {
        if (alive) setRequests(r);
      })
      .catch((e) => {
        if (alive) setError(errorDetail(e));
      });
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    if (isAdmin === true) return load();
    return undefined;
  }, [isAdmin, load]);

  const decide = async (approvalId: number, action: 'approve' | 'reject') => {
    setActingId(approvalId);
    setActionError(null);
    setActionDone(null);
    try {
      await api.post(`/api/approvals/${approvalId}/${action}`);
      setActionDone(action === 'approve' ? t('requests.approved') : t('requests.rejected'));
      load();
    } catch (e) {
      setActionError(errorDetail(e));
    } finally {
      setActingId(null);
    }
  };

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>{t('requests.title')}</h1>
          <p className="muted">{t('requests.sub')}</p>
        </div>
      </div>

      {isAdmin === null && <Loading label={t('activity.checkingPermission')} />}

      {isAdmin === false && (
        <div className="card empty-state">
          <div className="empty-state-title">{t('requests.needAdmin.title')}</div>
          <p className="muted">{t('requests.needAdmin.body')}</p>
        </div>
      )}

      {isAdmin === true && (
        <>
          {error && <ErrorBox message={error} />}
          {actionError && <ErrorBox message={actionError} />}
          {actionDone && <div className="result-box">{actionDone}</div>}
          {requests === null && !error && <Loading label={t('requests.loading')} />}
          {requests !== null && requests.length === 0 && (
            <div className="card empty-state">
              <div className="empty-state-title">{t('requests.empty.title')}</div>
              <p className="muted">{t('requests.empty.body')}</p>
            </div>
          )}
          {requests !== null && requests.length > 0 && (
            <div className="requests-list">
              {requests.map((r) => (
                <div className="card request-item" key={r.approval_id}>
                  <div className="request-main">
                    <div className="request-title">
                      {r.dashboard_title}
                      <span className="badge badge-blue">{t('requests.publishTo', { ws: r.target_workspace })}</span>
                    </div>
                    <div className="muted">
                      {t('requests.requester', { id: r.requested_by, time: formatDateTime(r.created_at) })}
                    </div>
                    {r.comment && r.comment.trim() !== '' && (
                      <div className="request-comment">{t('requests.comment', { comment: r.comment })}</div>
                    )}
                  </div>
                  <div className="request-actions">
                    <button
                      type="button"
                      className="btn btn-primary btn-sm"
                      disabled={actingId !== null}
                      onClick={() => void decide(r.approval_id, 'approve')}
                    >
                      {actingId === r.approval_id ? t('common.processing') : t('common.approve')}
                    </button>
                    <button
                      type="button"
                      className="btn btn-danger-ghost btn-sm"
                      disabled={actingId !== null}
                      onClick={() => void decide(r.approval_id, 'reject')}
                    >
                      {t('common.reject')}
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}
