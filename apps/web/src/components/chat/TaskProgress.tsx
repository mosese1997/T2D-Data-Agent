import type { PhaseEntry } from './useAgentTask';
import { StatusBadge } from '../common/ui';
import { useI18n } from '../../i18n';

interface TaskProgressProps {
  phases: PhaseEntry[];
  status: string | null;
  streamState: 'idle' | 'connecting' | 'open' | 'reconnecting';
  active: boolean;
}

export default function TaskProgress({ phases, status, streamState, active }: TaskProgressProps) {
  const { t } = useI18n();

  if (!active && phases.length === 0) return null;

  // 等待用户操作的状态必须醒目提示——不能让用户以为还在"进行中"干等。
  const waitingBanner =
    status === 'waiting_for_user'
      ? t('progress.waitingUser')
      : status === 'waiting_for_apply'
        ? t('progress.waitingApply')
        : null;

  return (
    <div className="task-progress">
      {waitingBanner && <div className="waiting-banner">{waitingBanner}</div>}
      <div className="task-progress-head">
        <span className="task-progress-title">{t('progress.title')}</span>
        {status && <StatusBadge status={status} />}
      </div>
      {active && streamState === 'connecting' && <div className="stream-hint">{t('progress.connecting')}</div>}
      {active && streamState === 'reconnecting' && <div className="stream-hint">{t('progress.reconnecting')}</div>}
      {active && phases.length === 0 && streamState === 'open' && (
        <div className="stream-hint">{t('progress.submitted')}</div>
      )}
      <div className="phase-list">
        {phases.map((p) => (
          <div key={p.phase} className={`phase ${p.status}`}>
            <div className="phase-head">
              <span className={`phase-icon ${p.status === 'running' ? 'spinner' : ''}`} aria-hidden="true">
                {p.status === 'done' ? '✓' : ''}
              </span>
              <span className="phase-label">{p.label}</span>
              {p.status === 'running' && <span className="muted phase-state">{t('progress.running')}</span>}
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
