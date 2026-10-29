import { Loading } from '../components/common/ui';
import RunsList from '../components/admin/RunsList';
import { useIsAdmin } from '../hooks/useIsAdmin';

/**
 * 任务运行活动（任务书 §13）：完整的运行列表接口仅对管理员开放；
 * 普通成员没有任务列表端点，如实提示，不展示任何伪造记录。
 */
export default function ActivityPage() {
  const isAdmin = useIsAdmin();

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>活动</h1>
          <p className="muted">系统内 Agent 任务的运行记录。点击行可进入执行 Trace（管理员）。</p>
        </div>
      </div>

      {isAdmin === null && <Loading label="正在确认权限…" />}

      {isAdmin === false && (
        <div className="card empty-state">
          <div className="empty-state-title">完整运行列表仅管理员可见</div>
          <p className="muted">
            任务运行列表与执行 Trace 属于管理台能力，仅管理员可查看。你可以在工作空间的看板对话中查看自己发起的任务进度。
          </p>
        </div>
      )}

      {isAdmin === true && <RunsList limit={50} />}
    </div>
  );
}
