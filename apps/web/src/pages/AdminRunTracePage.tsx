import { useEffect, useMemo, useState } from 'react';
import { Link, Navigate, useParams } from 'react-router-dom';
import { api } from '../api/client';
import { errorDetail } from '../api/error';
import type { AgentRunNode, RunTrace, ToolCallRow } from '../api/types';
import { useI18n } from '../i18n';
import { ErrorBox, Loading, RunStatusBadge, formatDateTime, prettyJson } from '../components/common/ui';
import { useIsAdmin } from '../hooks/useIsAdmin';

const TOOL_STATUS_CLASS: Record<string, string> = {
  ok: 'badge-green',
  error: 'badge-red',
  denied: 'badge-orange',
};

/** 执行 Trace（任务书 §13/§17）：任务概要 + agent_runs 时间线 + tool_calls 明细。仅管理员。 */
export default function AdminRunTracePage() {
  const { taskId } = useParams();
  const isAdmin = useIsAdmin();
  const id = Number(taskId);
  const [trace, setTrace] = useState<RunTrace | null>(null);
  const [error, setError] = useState<string | null>(null);
  const { t } = useI18n();

  useEffect(() => {
    if (isAdmin !== true || !Number.isFinite(id)) return;
    let alive = true;
    setTrace(null);
    setError(null);
    api
      .get<RunTrace>(`/api/admin/runs/${id}/trace`)
      .then((t) => {
        if (alive) setTrace(t);
      })
      .catch((e) => {
        if (alive) setError(errorDetail(e));
      });
    return () => {
      alive = false;
    };
  }, [id, isAdmin]);

  if (isAdmin === null) {
    return (
      <div className="page">
        <Loading label={t('activity.checkingPermission')} />
      </div>
    );
  }
  if (!isAdmin) {
    return <Navigate to="/activity" replace />;
  }

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>{t('trace.title', { id: Number.isFinite(id) ? id : '—' })}</h1>
          <p className="muted">
            <Link to="/admin">{t('trace.back')}</Link>
          </p>
        </div>
      </div>

      {error && <ErrorBox message={error} />}
      {trace === null && !error && <Loading label={t('trace.loading')} />}
      {trace !== null && (
        <div className="admin-sections">
          <TaskSummary trace={trace} />
          <AgentTimeline runs={trace.agent_runs} />
          <ToolCallsTable calls={trace.tool_calls} />
        </div>
      )}
    </div>
  );
}

/* ===================== 任务概要 ===================== */

function TaskSummary({ trace }: { trace: RunTrace }) {
  const { t } = useI18n();
  const { task } = trace;
  return (
    <div className="card">
      <h3>{t('trace.summary')}</h3>
      <div className="kv-list">
        <div className="kv-row">
          <span className="kv-key">{t('trace.type')}</span>
          <span>{task.type ?? '—'}</span>
        </div>
        <div className="kv-row">
          <span className="kv-key">{t('trace.status')}</span>
          <span>
            <RunStatusBadge status={task.status} />
          </span>
        </div>
        <div className="kv-row">
          <span className="kv-key">{t('trace.createdAt')}</span>
          <span>{formatDateTime(task.created_at)}</span>
        </div>
      </div>
      {task.error && <ErrorBox message={t('trace.taskError', { msg: task.error })} />}
      <JsonDetails label={t('trace.resultLabel')} value={task.result} />
      <JsonDetails label={t('trace.checkpointLabel')} value={task.checkpoint} />
    </div>
  );
}

/** 可折叠的 JSON 区块：长内容默认收起，展开后滚动查看 */
function JsonDetails({ label, value }: { label: string; value: unknown }) {
  const { t } = useI18n();
  const empty = value === null || value === undefined;
  return (
    <details className="json-details">
      <summary>
        {label}
        {empty && <span className="muted">{t('common.empty')}</span>}
      </summary>
      {!empty && <pre className="json-block">{prettyJson(value)}</pre>}
    </details>
  );
}

/* ===================== agent_runs 时间线 ===================== */

function AgentTimeline({ runs }: { runs: AgentRunNode[] }) {
  const { t } = useI18n();
  const childrenMap = useMemo(() => {
    const map = new Map<number, AgentRunNode[]>();
    for (const r of runs) {
      if (r.parent_run_id === null) continue;
      const list = map.get(r.parent_run_id) ?? [];
      list.push(r);
      map.set(r.parent_run_id, list);
    }
    return map;
  }, [runs]);

  return (
    <div className="card">
      <h3>{t('trace.timeline')}</h3>
      {runs.length === 0 && <div className="muted">{t('trace.noRuns')}</div>}
      {runs
        .filter((r) => r.parent_run_id === null)
        .map((root) => (
          <AgentNode key={root.id} node={root} childrenMap={childrenMap} />
        ))}
    </div>
  );
}

function AgentNode({
  node,
  childrenMap,
}: {
  node: AgentRunNode;
  childrenMap: Map<number, AgentRunNode[]>;
}) {
  const { t } = useI18n();
  const children = childrenMap.get(node.id) ?? [];
  const usage = node.token_usage ?? {};
  const tokens =
    typeof usage.total_tokens === 'number'
      ? t('trace.tokens', {
          total: usage.total_tokens.toLocaleString('en-US'),
          prompt: String(usage.prompt_tokens ?? '—'),
          completion: String(usage.completion_tokens ?? '—'),
        })
      : null;
  return (
    <div className="trace-node">
      <div className="trace-node-head">
        <span className="trace-agent">{t(`trace.agent.${node.agent_name}`, undefined, node.agent_name)}</span>
        <span className="badge badge-gray">{node.runtime}</span>
        <RunStatusBadge status={node.status} />
        <span className="muted">{node.model}</span>
      </div>
      <div className="muted trace-node-meta">
        {formatDateTime(node.started_at)} → {formatDateTime(node.finished_at)}
        {tokens && <span> · {tokens}</span>}
      </div>
      {children.map((c) => (
        <AgentNode key={c.id} node={c} childrenMap={childrenMap} />
      ))}
    </div>
  );
}

/* ===================== tool_calls 表格 ===================== */

function ToolCallsTable({ calls }: { calls: ToolCallRow[] }) {
  const { t } = useI18n();
  const [expandedSeq, setExpandedSeq] = useState<number | null>(null);

  return (
    <div className="card">
      <h3>{t('trace.toolCalls', { n: calls.length })}</h3>
      {calls.length === 0 && <div className="muted">{t('trace.noTools')}</div>}
      {calls.length > 0 && (
        <div className="table-scroll">
          <table className="data-table row-click">
            <thead>
              <tr>
                <th>#</th>
                <th>{t('trace.th.agent')}</th>
                <th>{t('trace.th.tool')}</th>
                <th>{t('trace.th.status')}</th>
                <th>{t('trace.th.latency')}</th>
              </tr>
            </thead>
            <tbody>
              {calls.map((c) => (
                <ToolCallRowView
                  key={c.seq}
                  call={c}
                  expanded={expandedSeq === c.seq}
                  onToggle={() => setExpandedSeq(expandedSeq === c.seq ? null : c.seq)}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function ToolCallRowView({
  call,
  expanded,
  onToggle,
}: {
  call: ToolCallRow;
  expanded: boolean;
  onToggle: () => void;
}) {
  const { t } = useI18n();
  return (
    <>
      <tr onClick={onToggle}>
        <td>{call.seq}</td>
        <td>{t(`trace.agent.${call.agent_name}`, undefined, call.agent_name)}</td>
        <td>{call.tool_name}</td>
        <td>
          <span className={`badge ${TOOL_STATUS_CLASS[call.status] ?? 'badge-gray'}`}>
            {t(`trace.tool.${call.status}`, undefined, call.status)}
          </span>
        </td>
        <td>{call.latency_ms} ms</td>
      </tr>
      {expanded && (
        <tr className="tool-io-row">
          <td colSpan={5}>
            {call.error && <ErrorBox message={t('trace.toolError', { msg: call.error })} />}
            <JsonDetails label={t('trace.inputLabel')} value={call.input} />
            <JsonDetails label={t('trace.outputLabel')} value={call.output} />
          </td>
        </tr>
      )}
    </>
  );
}
