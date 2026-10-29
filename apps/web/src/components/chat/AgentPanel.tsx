import { useEffect, useRef, useState } from 'react';
import type { ApplyPatchResponse } from '../../api/types';
import { useAgentTask } from './useAgentTask';
import TaskProgress from './TaskProgress';
import PatchProposal from './PatchProposal';
import ClarificationForm from './ClarificationForm';
import { ErrorBox } from '../common/ui';

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
        <button type="button" className="agent-toggle" onClick={onToggleCollapse} title="展开 Agent 面板">
          <span className="agent-toggle-icon" aria-hidden="true">‹</span>
          <span className="agent-toggle-text">Agent</span>
        </button>
      </aside>
    );
  }

  return (
    <aside className="agent-panel">
      <div className="agent-head">
        <span className="agent-title">Agent 助手</span>
        <div className="agent-head-actions">
          {task.active && (
            <button type="button" className="btn btn-danger-ghost btn-sm" onClick={() => void task.cancel()}>
              取消任务
            </button>
          )}
          <button type="button" className="agent-collapse-btn" onClick={onToggleCollapse} title="收起面板">
            <span aria-hidden="true">›</span>
          </button>
        </div>
      </div>

      <div className="agent-body" ref={bodyRef}>
        {task.messages.length === 0 && !task.active && (
          <div className="agent-welcome">
            {dashboardId === null ? (
              <p>这是一个空白看板。告诉 Agent 你想看什么，例如：</p>
            ) : (
              <p>和 Agent 对话，修改当前看板。例如：</p>
            )}
            <ul>
              <li>「最近 7 天各国 GMV 趋势，再给我一个 GMV 总量」</li>
              <li>「按渠道拆分订单量，做成柱状图」</li>
              <li>「加一段口径说明文字」</li>
            </ul>
            <p className="muted">Agent 会生成查询、执行并提议看板修改，由你确认应用。</p>
          </div>
        )}

        <div className="msg-list">
          {task.messages.map((m) => (
            <div key={m.id} className={`msg ${m.role === 'user' ? 'msg-user' : 'msg-assistant'}`}>
              {m.content}
            </div>
          ))}
        </div>

        {task.resultText && <div className="result-box">{task.resultText}</div>}
        {task.taskError && <ErrorBox message={`任务失败：${task.taskError}`} />}

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
              ? '等你回复上方的问题后任务才会继续…'
              : task.status === 'waiting_for_apply'
                ? '候选变更待应用（见上方卡片），应用后即可继续对话…'
                : task.active
                  ? '任务进行中…（可点击取消）'
                  : dashboardId === null
                    ? '描述你想看的看板，例如：最近 7 天各国 GMV 趋势'
                    : '描述你想对看板做的修改…'
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
          {task.busy ? '提交中…' : '发送'}
        </button>
      </div>
    </aside>
  );
}
