import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../../api/client';
import { ApiError, errorMessage } from '../../api/error';
import { SseClient, type SseEvent } from '../../api/sse';
import type { ApplyPatchResponse, Canvas, ChatMessage, Task, TaskStatus } from '../../api/types';
import { useAuthStore } from '../../stores/auth';
import { invalidateSourceRows } from '../../hooks/useSourceRows';

export interface ChatMsg {
  id: string;
  role: 'user' | 'assistant';
  content: string;
}

export interface ToolEntry {
  tool: string;
  agent: string | null;
  status: 'running' | 'done';
  summary: string | null;
}

export interface PhaseEntry {
  phase: string;
  label: string;
  status: 'running' | 'done';
  summary: string | null;
  tools: ToolEntry[];
}

export interface Proposal {
  patchId: number;
  diffSummary: string;
  previewCanvas: Canvas | null;
}

const TERMINAL: TaskStatus[] = ['succeeded', 'failed', 'cancelled', 'interrupted'];
const ACTIVE: TaskStatus[] = ['queued', 'running', 'waiting_for_user', 'waiting_for_apply'];

const PHASE_LABELS: Record<string, string> = {
  main: 'Agent 推理',
  intent_parse: '解析意图',
  sql_generate: '生成查询',
  query: '执行查询',
  patch_propose: '生成修改方案',
  clarify: '澄清需求',
  plan: '规划',
  validate: '校验',
  analysis: '结果分析',
};

function phaseLabel(phase: string): string {
  return PHASE_LABELS[phase] ?? phase;
}

export function isTaskActive(status: TaskStatus | null): boolean {
  return status !== null && ACTIVE.includes(status);
}

function describeResult(result: unknown): string | null {
  if (result === null || result === undefined) return null;
  if (typeof result === 'string') return result;
  if (typeof result === 'object') {
    const r = result as Record<string, unknown>;
    if (typeof r.message === 'string') return r.message;
    if (typeof r.summary === 'string') return r.summary;
    try {
      return JSON.stringify(result);
    } catch {
      return String(result);
    }
  }
  return String(result);
}

// ---- 进行中任务的会话内持久化（刷新页面后可重新挂载 SSE） ----
interface StoredTask {
  conversationId: number;
  taskId: number;
}

function saveSession(key: string, v: StoredTask): void {
  try {
    sessionStorage.setItem(key, JSON.stringify(v));
  } catch {
    // 忽略
  }
}
function loadSession(key: string): StoredTask | null {
  try {
    const raw = sessionStorage.getItem(key);
    return raw ? (JSON.parse(raw) as StoredTask) : null;
  } catch {
    return null;
  }
}
function clearSession(key: string): void {
  try {
    sessionStorage.removeItem(key);
  } catch {
    // 忽略
  }
}

export interface UseAgentTaskParams {
  workspaceId: number;
  /** null 表示「新建看板」模式：会话不绑定看板，patch 应用后跳转到新看板 */
  dashboardId: number | null;
  onPatchApplied: (res: ApplyPatchResponse) => void;
}

export function useAgentTask({ workspaceId, dashboardId, onPatchApplied }: UseAgentTaskParams) {
  const [conversationId, setConversationId] = useState<number | null>(null);
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [phases, setPhases] = useState<PhaseEntry[]>([]);
  const [status, setStatus] = useState<TaskStatus | null>(null);
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const [clarification, setClarification] = useState<string | null>(null);
  const [taskError, setTaskError] = useState<string | null>(null);
  const [resultText, setResultText] = useState<string | null>(null);
  const [sendError, setSendError] = useState<string | null>(null);
  const [patchError, setPatchError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [streamState, setStreamState] = useState<'idle' | 'connecting' | 'open' | 'reconnecting'>('idle');

  const statusRef = useRef<TaskStatus | null>(null);
  const lastSeqRef = useRef(0);
  const clientRef = useRef<SseClient | null>(null);
  const convRef = useRef<number | null>(null);
  const taskIdRef = useRef<number | null>(null);
  const msgIdRef = useRef(0);

  const sessionKey =
    dashboardId !== null ? `t2d.task.w${workspaceId}.d${dashboardId}` : `t2d.task.w${workspaceId}.new`;

  const applyStatus = (s: TaskStatus) => {
    statusRef.current = s;
    setStatus(s);
  };

  const appendUser = useCallback((content: string) => {
    setMessages((prev) => [...prev, { id: `u${++msgIdRef.current}`, role: 'user', content }]);
  }, []);

  const appendAssistant = useCallback((content: string) => {
    // 事件重放可能与已拉取的会话消息重复，按内容去重
    setMessages((prev) =>
      prev.some((m) => m.role === 'assistant' && m.content === content)
        ? prev
        : [...prev, { id: `a${++msgIdRef.current}`, role: 'assistant', content }],
    );
  }, []);

  const stopStream = useCallback(() => {
    clientRef.current?.stop();
    clientRef.current = null;
    setStreamState('idle');
  }, []);

  const reloadMessages = useCallback(async () => {
    const convId = convRef.current;
    if (convId === null) return;
    try {
      const list = await api.get<ChatMessage[]>(`/api/conversations/${convId}/messages`);
      setMessages(
        list.map((m) => ({ id: `s${m.seq}`, role: m.role === 'user' ? ('user' as const) : ('assistant' as const), content: m.content })),
      );
    } catch {
      // 拉取失败时保留本地消息
    }
  }, []);

  const reduceEvent = useCallback(
    (ev: SseEvent) => {
      // 按 seq 去重（重连补读 / 事件重放）
      if (ev.id !== null) {
        const seq = Number(ev.id);
        if (Number.isFinite(seq)) {
          if (seq <= lastSeqRef.current) return;
          lastSeqRef.current = seq;
        }
      }
      let data: Record<string, unknown> = {};
      if (ev.data) {
        try {
          data = JSON.parse(ev.data) as Record<string, unknown>;
        } catch {
          data = {};
        }
      }
      switch (ev.event) {
        case 'phase.started': {
          const phase = String(data.phase ?? '');
          if (!phase) break;
          setPhases((prev) => {
            const idx = prev.findIndex((p) => p.phase === phase);
            if (idx >= 0) {
              const next = [...prev];
              next[idx] = { ...next[idx], status: 'running' };
              return next;
            }
            return [...prev, { phase, label: phaseLabel(phase), status: 'running', summary: null, tools: [] }];
          });
          break;
        }
        case 'phase.completed': {
          const phase = String(data.phase ?? '');
          const summary = data.summary == null ? null : String(data.summary);
          setPhases((prev) =>
            prev.map((p) => (p.phase === phase ? { ...p, status: 'done', summary: summary ?? p.summary } : p)),
          );
          break;
        }
        case 'tool.started': {
          const tool = String(data.tool ?? '');
          if (!tool) break;
          const agent = data.agent == null ? null : String(data.agent);
          setPhases((prev) => {
            if (prev.length === 0) {
              return [
                { phase: '_root', label: '执行中', status: 'running', summary: null, tools: [{ tool, agent, status: 'running', summary: null }] },
              ];
            }
            const next = [...prev];
            let idx = next.length - 1;
            for (let i = next.length - 1; i >= 0; i--) {
              if (next[i].status === 'running') {
                idx = i;
                break;
              }
            }
            next[idx] = { ...next[idx], tools: [...next[idx].tools, { tool, agent, status: 'running', summary: null }] };
            return next;
          });
          break;
        }
        case 'tool.completed': {
          const tool = String(data.tool ?? '');
          const summary = data.summary == null ? null : String(data.summary);
          setPhases((prev) => {
            for (let i = prev.length - 1; i >= 0; i--) {
              const tools = prev[i].tools;
              for (let j = tools.length - 1; j >= 0; j--) {
                if (tools[j].tool === tool && tools[j].status === 'running') {
                  const next = [...prev];
                  next[i] = {
                    ...next[i],
                    tools: [...tools.slice(0, j), { ...tools[j], status: 'done', summary: summary ?? tools[j].summary }, ...tools.slice(j + 1)],
                  };
                  return next;
                }
              }
            }
            return prev;
          });
          break;
        }
        case 'agent.message': {
          const content = data.content == null ? '' : String(data.content);
          if (content) appendAssistant(content);
          break;
        }
        case 'clarification.requested': {
          setClarification(String(data.question ?? '请补充更多信息'));
          applyStatus('waiting_for_user');
          break;
        }
        case 'patch.proposed': {
          setProposal({
            patchId: Number(data.patch_id ?? 0),
            diffSummary: String(data.diff_summary ?? ''),
            previewCanvas: (data.preview_canvas ?? null) as Canvas | null,
          });
          setPatchError(null);
          applyStatus('waiting_for_apply');
          break;
        }
        case 'task.status_changed': {
          const s = String(data.status ?? '') as TaskStatus;
          if (s) applyStatus(s);
          break;
        }
        case 'task.completed': {
          applyStatus('succeeded');
          setResultText(describeResult(data.result));
          clearSession(sessionKey);
          stopStream();
          void reloadMessages();
          break;
        }
        case 'task.failed': {
          applyStatus('failed');
          setTaskError(String(data.error ?? '任务执行失败'));
          clearSession(sessionKey);
          stopStream();
          break;
        }
        case 'task.cancelled': {
          applyStatus('cancelled');
          clearSession(sessionKey);
          stopStream();
          break;
        }
        default:
          break;
      }
    },
    [appendAssistant, reloadMessages, sessionKey, stopStream],
  );

  /** 从 GET /api/tasks/{id} 拉取事件补齐缺口（SSE 重连前 / 页面刷新重新挂载时） */
  const syncMissedEvents = useCallback(
    async (taskId: number) => {
      try {
        const task = await api.get<Task>(`/api/tasks/${taskId}`);
        for (const ev of task.events ?? []) {
          reduceEvent({ id: String(ev.seq), event: ev.event, data: JSON.stringify(ev.data ?? {}) });
        }
        applyStatus(task.status);
        if (TERMINAL.includes(task.status)) {
          if (task.error) setTaskError(task.error);
          if (task.status === 'succeeded' && task.result != null) setResultText(describeResult(task.result));
          stopStream();
        }
      } catch {
        // 补读失败不阻断后续 SSE
      }
    },
    [reduceEvent, stopStream],
  );

  const startStream = useCallback(
    (taskId: number) => {
      stopStream();
      const client = new SseClient(`/api/tasks/${taskId}/events`, {
        getToken: () => useAuthStore.getState().token,
        onEvent: reduceEvent,
        shouldReconnect: () => !TERMINAL.includes(statusRef.current ?? 'running'),
        onStateChange: (s) => setStreamState(s),
        onReconnect: () => syncMissedEvents(taskId),
      });
      clientRef.current = client;
      client.start();
    },
    [reduceEvent, stopStream, syncMissedEvents],
  );

  const attachTask = useCallback(
    async (conversationId: number, taskId: number) => {
      convRef.current = conversationId;
      setConversationId(conversationId);
      taskIdRef.current = taskId;
      saveSession(sessionKey, { conversationId, taskId });
      applyStatus('running');
      await syncMissedEvents(taskId);
      if (!TERMINAL.includes(statusRef.current ?? 'running')) startStream(taskId);
    },
    [sessionKey, startStream, syncMissedEvents],
  );

  // 挂载时恢复进行中的任务（页面刷新场景）
  useEffect(() => {
    const saved = loadSession(sessionKey);
    if (!saved) return;
    let alive = true;
    void (async () => {
      try {
        const task = await api.get<Task>(`/api/tasks/${saved.taskId}`);
        if (!alive) return;
        if (TERMINAL.includes(task.status)) {
          clearSession(sessionKey);
          return;
        }
        convRef.current = saved.conversationId;
        setConversationId(saved.conversationId);
        await reloadMessages();
        await attachTask(saved.conversationId, saved.taskId);
      } catch {
        clearSession(sessionKey);
      }
    })();
    return () => {
      alive = false;
      stopStream();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionKey]);

  const send = useCallback(
    async (content: string) => {
      const text = content.trim();
      if (!text || busy || isTaskActive(statusRef.current)) return;
      setBusy(true);
      setSendError(null);
      setTaskError(null);
      setResultText(null);
      setProposal(null);
      setClarification(null);
      setPatchError(null);
      setPhases([]);
      appendUser(text);
      try {
        let convId = convRef.current;
        if (convId === null) {
          const created = await api.post<{ id: number }>('/api/conversations', {
            workspace_id: workspaceId,
            ...(dashboardId !== null ? { dashboard_id: dashboardId } : {}),
          });
          convId = created.id;
          convRef.current = convId;
          setConversationId(convId);
        }
        const resp = await api.post<{ task_id: number; message_seq: number }>(`/api/conversations/${convId}/messages`, {
          content: text,
        });
        lastSeqRef.current = 0;
        taskIdRef.current = resp.task_id;
        applyStatus('queued');
        saveSession(sessionKey, { conversationId: convId, taskId: resp.task_id });
        startStream(resp.task_id);
      } catch (e) {
        setSendError(errorMessage(e));
      } finally {
        setBusy(false);
      }
    },
    [appendUser, busy, dashboardId, sessionKey, startStream, workspaceId],
  );

  const answer = useCallback(
    async (content: string) => {
      const text = content.trim();
      const taskId = taskIdRef.current;
      if (!text || taskId === null) return;
      setClarification(null);
      setSendError(null);
      appendUser(text);
      applyStatus('running');
      try {
        await api.post(`/api/tasks/${taskId}/answer`, { content: text });
      } catch (e) {
        setSendError(errorMessage(e));
      }
    },
    [appendUser],
  );

  const cancel = useCallback(async () => {
    const taskId = taskIdRef.current;
    if (taskId === null) return;
    clearSession(sessionKey);
    try {
      await api.post(`/api/tasks/${taskId}/cancel`, {});
    } catch {
      // 取消失败时交给 SSE / 任务状态兜底
    }
    applyStatus('cancelled');
    stopStream();
  }, [sessionKey, stopStream]);

  const applyPatch = useCallback(async () => {
    if (proposal === null) return;
    setPatchError(null);
    try {
      const res = await api.post<ApplyPatchResponse>(`/api/patches/${proposal.patchId}/apply`, {});
      invalidateSourceRows();
      setProposal(null);
      applyStatus('succeeded');
      clearSession(sessionKey);
      stopStream();
      onPatchApplied(res);
    } catch (e) {
      setPatchError(
        e instanceof ApiError && e.status === 409
          ? '版本冲突：看板已被其他修改更新，请刷新页面后重试'
          : `应用修改失败：${errorMessage(e)}`,
      );
    }
  }, [onPatchApplied, proposal, sessionKey, stopStream]);

  const rejectPatch = useCallback(async () => {
    if (proposal === null) return;
    setPatchError(null);
    try {
      await api.post(`/api/patches/${proposal.patchId}/reject`, {});
      setProposal(null);
      applyStatus('cancelled');
      clearSession(sessionKey);
      stopStream();
    } catch (e) {
      setPatchError(`拒绝修改失败：${errorMessage(e)}`);
    }
  }, [proposal, sessionKey, stopStream]);

  const active = isTaskActive(status);

  return {
    conversationId,
    messages,
    phases,
    status,
    active,
    proposal,
    clarification,
    taskError,
    resultText,
    sendError,
    patchError,
    busy,
    streamState,
    send,
    answer,
    cancel,
    applyPatch,
    rejectPatch,
  };
}

export type AgentTask = ReturnType<typeof useAgentTask>;
