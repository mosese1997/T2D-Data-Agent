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

  // 等待用户操作的状态必须醒目提示——不能让用户以为还在"进行中"干等。
  const waitingBanner =
    status === 'waiting_for_user'
      ? '⏸ Agent 在等你回复：请在上方「需要澄清」的问题框里作答，任务才会继续。'
      : status === 'waiting_for_apply'
        ? '🔔 候选变更已就绪：请在上方预览卡片中点击「应用修改」，画布才会更新。'
        : null;

  return (
    <div className="task-progress">
      {waitingBanner && <div className="waiting-banner">{waitingBanner}</div>}
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
