import { useCallback, useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { api } from '../api/client';
import { errorMessage } from '../api/error';
import type { ApplyPatchResponse, Dashboard } from '../api/types';
import { useWorkspaces } from '../hooks/useWorkspaces';
import { recordRecent } from '../stores/recent';
import DashboardCanvas from '../components/canvas/DashboardCanvas';
import AgentPanel from '../components/chat/AgentPanel';
import { ErrorBox, Loading, StatusBadge } from '../components/common/ui';

export default function StudioPage() {
  const { workspaceId: wsIdParam, dashboardId: dashIdParam } = useParams();
  const workspaceId = Number(wsIdParam);
  const dashboardId = dashIdParam !== undefined ? Number(dashIdParam) : null;
  const isNew = dashboardId === null;
  const navigate = useNavigate();

  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [panelCollapsed, setPanelCollapsed] = useState(false);
  const { workspaces } = useWorkspaces();
  const workspaceName = workspaces?.find((w) => w.id === workspaceId)?.name ?? `工作空间 #${workspaceId}`;

  const loadDashboard = useCallback(async () => {
    if (dashboardId === null) {
      setDashboard(null);
      return;
    }
    try {
      setLoadError(null);
      const d = await api.get<Dashboard>(`/api/dashboards/${dashboardId}`);
      setDashboard(d);
      recordRecent({ workspaceId, workspaceName, dashboardId: d.id, title: d.title });
    } catch (e) {
      setLoadError(errorMessage(e));
    }
  }, [dashboardId, workspaceId, workspaceName]);

  useEffect(() => {
    void loadDashboard();
  }, [loadDashboard]);

  const handlePatchApplied = useCallback(
    (res: ApplyPatchResponse) => {
      if (isNew) {
        // 新建看板模式：应用成功后跳转到新看板的 Studio
        navigate(`/w/${workspaceId}/d/${res.dashboard_id}`, { replace: true });
      } else {
        void loadDashboard();
      }
    },
    [isNew, navigate, workspaceId, loadDashboard],
  );

  if (Number.isNaN(workspaceId) || (dashIdParam !== undefined && Number.isNaN(dashboardId))) {
    return (
      <div className="page">
        <ErrorBox message="无效的地址参数" />
      </div>
    );
  }

  return (
    <div className="studio">
      <div className="studio-main">
        <div className="studio-topbar">
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => navigate(`/w/${workspaceId}`)}>
            ← 返回
          </button>
          <div className="studio-title-wrap">
            <h1 className="studio-title">{dashboard?.title ?? (isNew ? '新建看板' : '加载中…')}</h1>
            {dashboard && (
              <span className="studio-meta">
                <StatusBadge status={dashboard.status} />
                <span className="muted">v{dashboard.revision}</span>
              </span>
            )}
          </div>
        </div>
        {loadError && <ErrorBox message={loadError} />}
        <div className="studio-canvas">
          {isNew ? (
            <div className="canvas-empty">
              <div className="canvas-empty-title">空白画布</div>
              <p>在右侧 Agent 面板描述你想看的指标（例如「最近 7 天各国 GMV 趋势」），Agent 会自动生成查询并搭建看板。</p>
            </div>
          ) : dashboard ? (
            <DashboardCanvas canvas={dashboard.canvas} />
          ) : (
            !loadError && <Loading label="正在加载看板…" />
          )}
        </div>
      </div>

      <AgentPanel
        workspaceId={workspaceId}
        dashboardId={dashboardId}
        collapsed={panelCollapsed}
        onToggleCollapse={() => setPanelCollapsed((v) => !v)}
        onPatchApplied={handlePatchApplied}
      />
    </div>
  );
}
