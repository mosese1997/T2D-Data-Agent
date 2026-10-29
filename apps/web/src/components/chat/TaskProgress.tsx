import type { PhaseEntry } from './useAgentTask';
import { StatusBadge } from '../common/ui';

interface TaskProgressProps {
  phases: PhaseEntry[];
  status: string | null;
  streamState: 'idle' | 'connecting' | 'open' | 'reconnecting';
  active: boolean;
}

export default function TaskProgress({ phases, status, streamState, active }: TaskProgressProps) {
  if (!active && phases.length === 0) return null;

  return (
    <div className="task-progress">
      <div className="task-progress-head">
        <span className="task-progress-title">任务进度</span>
        {status && <StatusBadge status={status} />}
      </div>
      {active && streamState === 'connecting' && <div className="stream-hint">正在连接事件流…</div>}
      {active && streamState === 'reconnecting' && <div className="stream-hint">连接中断，正在重连并补读事件…</div>}
      {active && phases.length === 0 && streamState === 'open' && (
        <div className="stream-hint">已提交，等待 Agent 响应…</div>
      )}
      <div className="phase-list">
        {phases.map((p) => (
          <div key={p.phase} className={`phase ${p.status}`}>
            <div className="phase-head">
              <span className={`phase-icon ${p.status === 'running' ? 'spinner' : ''}`} aria-hidden="true">
                {p.status === 'done' ? '✓' : ''}
              </span>
              <span className="phase-label">{p.label}</span>
              {p.status === 'running' && <span className="muted phase-state">进行中</span>}
            </div>
            {p.summary && <div className="phase-summary">{p.summary}</div>}
            {p.tools.length > 0 && (
              <div className="tool-list">
                {p.tools.map((t, i) => (
                  <div key={`${t.tool}-${i}`} className={`tool ${t.status}`}>
                    <span className={`tool-icon ${t.status === 'running' ? 'spinner' : ''}`} aria-hidden="true">
                      {t.status === 'done' ? '✓' : ''}
                    </span>
                    <span className="tool-name">{t.tool}</span>
                    {t.agent && <span className="tool-agent muted">{t.agent}</span>}
                    {t.summary && <span className="tool-summary">{t.summary}</span>}
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
