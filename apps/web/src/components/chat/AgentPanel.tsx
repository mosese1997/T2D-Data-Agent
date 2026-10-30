import { useEffect, useRef, useState } from 'react';
import type { ApplyPatchResponse } from '../../api/types';
import { useI18n } from '../../i18n';
import { useAgentTask } from './useAgentTask';
import TaskProgress from './TaskProgress';
import PatchProposal from './PatchProposal';
import ClarificationForm from './ClarificationForm';
import { ErrorBox } from '../common/ui';

/** 最小内联格式化：**加粗** → <strong>，其余原样（聊天气泡用） */
function inlineBold(text: string) {
  const parts = text.split(/\*\*([^*]+)\*\*/g);
  return parts.map((part, i) =>
    i % 2 === 1 ? <strong key={i}>{part}</strong> : <span key={i}>{part}</span>,
  );
}

interface AgentPanelProps {
  workspaceId: number;
  /** null = 新建看板模式 */
  dashboardId: number | null;
  collapsed: boolean;
  onToggleCollapse: () => void;
  onPatchApplied: (res: ApplyPatchResponse) => void;
}

export default function AgentPanel({ workspaceId, dashboardId, collapsed, onToggleCollapse, onPatchApplied }: AgentPanelProps) {
  const task = useAgentTask({ workspaceId, dashboardId, onPatchApplied });
  const [input, setInput] = useState('');
  const bodyRef = useRef<HTMLDivElement>(null);
  const { t } = useI18n();

  // 新消息 / 进度变化时滚动到底部
  useEffect(() => {
    const el = bodyRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [task.messages, task.phases, task.proposal, task.clarification, task.resultText, task.taskError, task.sendError]);

  const canSend = !task.busy && !task.active && task.clarification === null;

  const submit = () => {
    const text = input.trim();
    if (!text || !canSend) return;
    setInput('');
    void task.send(text);
  };

  if (collapsed) {
    return (
      <aside className="agent-panel collapsed">
        <button type="button" className="agent-toggle" onClick={onToggleCollapse} title={t('agent.expand')}>
          <span className="agent-toggle-icon" aria-hidden="true">‹</span>
          <span className="agent-toggle-text">Agent</span>
        </button>
      </aside>
    );
  }

  return (
    <aside className="agent-panel">
      <div className="agent-head">
        <span className="agent-title">{t('agent.title')}</span>
        <div className="agent-head-actions">
          {task.active && (
            <button type="button" className="btn btn-danger-ghost btn-sm" onClick={() => void task.cancel()}>
              {t('agent.cancelTask')}
            </button>
          )}
          <button type="button" className="agent-collapse-btn" onClick={onToggleCollapse} title={t('agent.collapse')}>
            <span aria-hidden="true">›</span>
          </button>
        </div>
      </div>

      <div className="agent-body" ref={bodyRef}>
        {task.messages.length === 0 && !task.active && (
          <div className="agent-welcome">
            {dashboardId === null ? (
              <p>{t('agent.welcomeNew')}</p>
            ) : (
              <p>{t('agent.welcomeExisting')}</p>
            )}
            <ul>
              <li>{t('agent.example1')}</li>
              <li>{t('agent.example2')}</li>
              <li>{t('agent.example3')}</li>
            </ul>
            <p className="muted">{t('agent.welcomeHint')}</p>
          </div>
        )}

        <div className="msg-list">
          {task.messages.map((m) => (
            <div key={m.id} className={`msg ${m.role === 'user' ? 'msg-user' : 'msg-assistant'}`}>
              {inlineBold(m.content)}
            </div>
          ))}
        </div>

        {task.resultText && <div className="result-box">{inlineBold(task.resultText)}</div>}
        {task.taskError && <ErrorBox message={t('agent.taskFailed', { msg: task.taskError })} />}

        <TaskProgress phases={task.phases} status={task.status} streamState={task.streamState} active={task.active} />

        {task.clarification !== null && <ClarificationForm question={task.clarification} onSubmit={task.answer} />}

        {task.proposal && (
          <PatchProposal proposal={task.proposal} error={task.patchError} onApply={task.applyPatch} onReject={task.rejectPatch} />
        )}

        {task.sendError && <ErrorBox message={task.sendError} />}
      </div>

      <div className="agent-input">
        <textarea
          value={input}
          rows={2}
          placeholder={
            task.status === 'waiting_for_user'
              ? t('agent.placeholder.waitingUser')
              : task.status === 'waiting_for_apply'
                ? t('agent.placeholder.waitingApply')
                : task.active
                  ? t('agent.placeholder.running')
                  : dashboardId === null
                    ? t('agent.placeholder.new')
                    : t('agent.placeholder.edit')
          }
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
        />
        <button type="button" className="btn btn-primary" disabled={!canSend || !input.trim()} onClick={submit}>
          {task.busy ? t('common.submitting') : t('common.send')}
        </button>
      </div>
    </aside>
  );
}
