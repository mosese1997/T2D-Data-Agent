import { useCallback, useEffect, useState } from 'react';
import { api } from '../api/client';
import { errorDetail } from '../api/error';
import type { ApprovalRequest } from '../api/types';
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
      setActionDone(action === 'approve' ? '已批准，看板已发布到目标空间。' : '已拒绝该发布请求。');
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
          <h1>发布审批</h1>
          <p className="muted">目标业务空间的看板发布请求。批准后，看板快照（含数据源与结果文件）会发布到目标空间。</p>
        </div>
      </div>

      {isAdmin === null && <Loading label="正在确认权限…" />}

      {isAdmin === false && (
        <div className="card empty-state">
          <div className="empty-state-title">需要管理员权限</div>
          <p className="muted">发布审批仅目标业务空间的管理员可见与操作。你当前不是任何空间的管理员。</p>
        </div>
      )}

      {isAdmin === true && (
        <>
          {error && <ErrorBox message={error} />}
          {actionError && <ErrorBox message={actionError} />}
          {actionDone && <div className="result-box">{actionDone}</div>}
          {requests === null && !error && <Loading label="加载待审批请求…" />}
          {requests !== null && requests.length === 0 && (
            <div className="card empty-state">
              <div className="empty-state-title">暂无待审批请求</div>
              <p className="muted">有分析师向你所在业务空间发起发布请求时会出现在这里。</p>
            </div>
          )}
          {requests !== null && requests.length > 0 && (
            <div className="requests-list">
              {requests.map((r) => (
                <div className="card request-item" key={r.approval_id}>
                  <div className="request-main">
                    <div className="request-title">
                      {r.dashboard_title}
                      <span className="badge badge-blue">发布 → {r.target_workspace}</span>
                    </div>
                    <div className="muted">
                      请求人：用户 #{r.requested_by} · {formatDateTime(r.created_at)}
                    </div>
                    {r.comment && r.comment.trim() !== '' && <div className="request-comment">备注：{r.comment}</div>}
                  </div>
                  <div className="request-actions">
                    <button
                      type="button"
                      className="btn btn-primary btn-sm"
                      disabled={actingId !== null}
                      onClick={() => void decide(r.approval_id, 'approve')}
                    >
                      {actingId === r.approval_id ? '处理中…' : '批准'}
                    </button>
                    <button
                      type="button"
                      className="btn btn-danger-ghost btn-sm"
                      disabled={actingId !== null}
                      onClick={() => void decide(r.approval_id, 'reject')}
                    >
                      拒绝
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
