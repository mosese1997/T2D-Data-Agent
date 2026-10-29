import { useEffect, useState } from 'react';
import { Navigate } from 'react-router-dom';
import { api } from '../api/client';
import { errorDetail } from '../api/error';
import type { AgentBudget, AgentConfigResponse, EvalRunEntry, KnowledgeIndex } from '../api/types';
import RunsList from '../components/admin/RunsList';
import { ErrorBox, Loading, formatDateTime } from '../components/common/ui';
import { useIsAdmin } from '../hooks/useIsAdmin';

type AdminTab = 'config' | 'knowledge' | 'runs' | 'evals';

const TABS: { key: AdminTab; label: string }[] = [
  { key: 'config', label: 'Agent 配置' },
  { key: 'knowledge', label: '知识索引' },
  { key: 'runs', label: '运行' },
  { key: 'evals', label: '评测' },
];

/** 管理台（任务书 §13）：仅管理员可见，非管理员重定向到活动页（那里有权限提示）。 */
export default function AdminPage() {
  const isAdmin = useIsAdmin();
  const [tab, setTab] = useState<AdminTab>('config');

  if (isAdmin === null) {
    return (
      <div className="page">
        <Loading label="正在确认权限…" />
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
          <h1>Agent 管理台</h1>
          <p className="muted">运行时配置、知识索引、任务运行与评测——全部来自真实后端数据。</p>
        </div>
      </div>

      <nav className="section-tabs">
        {TABS.map((t) => (
          <button
            type="button"
            key={t.key}
            className={`tab ${tab === t.key ? 'active' : ''}`}
            onClick={() => setTab(t.key)}
          >
            {t.label}
          </button>
        ))}
      </nav>

      {tab === 'config' && <AgentConfigSection />}
      {tab === 'knowledge' && <KnowledgeIndexSection />}
      {tab === 'runs' && <RunsSection />}
      {tab === 'evals' && <EvalsSection />}
    </div>
  );
}

/* ===================== Agent 配置 ===================== */

const EXTRA_BUDGET_LABELS: Record<string, string> = {
  max_tokens_per_task: '单任务 token 上限',
  max_sql_repairs: 'SQL 修复上限',
  sandbox_timeout_s: '沙箱超时（秒）',
};

const AGENT_LABELS: Record<string, string> = {
  main_agent: '主 Agent',
  query_agent: '查询 Agent',
  analysis_agent: '分析 Agent',
};

function formatCapabilityValue(v: unknown): string {
  if (typeof v === 'boolean') return v ? '是' : '否';
  return String(v);
}

function AgentConfigSection() {
  const [config, setConfig] = useState<AgentConfigResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [switching, setSwitching] = useState<string | null>(null);
  const [switchError, setSwitchError] = useState<string | null>(null);
  const [switchDone, setSwitchDone] = useState<string | null>(null);

  const load = () => {
    let alive = true;
    setConfig(null);
    setError(null);
    api
      .get<AgentConfigResponse>('/api/admin/agent-config')
      .then((c) => {
        if (alive) setConfig(c);
      })
      .catch((e) => {
        if (alive) setError(errorDetail(e));
      });
    return () => {
      alive = false;
    };
  };

  useEffect(() => load(), []);

  const switchRuntime = async (runtime: 'toolloop' | 'swarmflow') => {
    setSwitching(runtime);
    setSwitchError(null);
    setSwitchDone(null);
    try {
      await api.post<{ runtime: string }>('/api/admin/agent-config/runtime', { runtime });
      setSwitchDone(`运行时已切换为 ${runtime}。`);
      load();
    } catch (e) {
      // 后端会拒绝未接入的 runtime（409），如实展示原因
      setSwitchError(errorDetail(e));
    } finally {
      setSwitching(null);
    }
  };

  if (error) return <ErrorBox message={error} />;
  if (config === null) return <Loading label="加载 Agent 配置…" />;

  const agent = config.config.agent;
  const budgets: { key: string; budget: AgentBudget }[] = [
    { key: 'main_agent', budget: agent.main_agent ?? {} },
    { key: 'query_agent', budget: agent.query_agent ?? {} },
    { key: 'analysis_agent', budget: agent.analysis_agent ?? {} },
  ];
  const knownBudgetKeys = new Set(['prompt_version', 'max_steps', 'max_tool_calls']);

  return (
    <div className="admin-sections">
      <div className="card">
        <h3>当前运行时</h3>
        <div className="kv-list">
          <div className="kv-row">
            <span className="kv-key">runtime</span>
            <span>
              <span className="badge badge-blue">{agent.runtime}</span>
            </span>
          </div>
          <div className="kv-row">
            <span className="kv-key">模型</span>
            <span>{agent.model}</span>
          </div>
          <div className="kv-row">
            <span className="kv-key">采样参数</span>
            <span>
              temperature {agent.temperature ?? '—'} · max_tokens {agent.max_tokens ?? '—'}
            </span>
          </div>
        </div>

        <h4>运行时切换</h4>
        <div className="runtime-switch">
          <button
            type="button"
            className="btn btn-primary btn-sm"
            disabled={switching !== null || agent.runtime === 'toolloop'}
            onClick={() => void switchRuntime('toolloop')}
          >
            {agent.runtime === 'toolloop' ? '当前：toolloop' : '切换到 toolloop'}
          </button>
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            disabled={switching !== null || agent.runtime === 'swarmflow'}
            onClick={() => void switchRuntime('swarmflow')}
          >
            {agent.runtime === 'swarmflow' ? '当前：swarmflow' : '切换到 swarmflow'}
          </button>
          <span className="muted">swarmflow 适配器尚未接入主链路，切换请求会被后端拒绝（409），原因将如实显示。</span>
        </div>
        {switching !== null && <Loading label="正在切换…" />}
        {switchError && <ErrorBox message={switchError} />}
        {switchDone && <div className="result-box">{switchDone}</div>}
      </div>

      <div className="card">
        <h3>Agent 预算</h3>
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th>Agent</th>
                <th>Prompt 版本</th>
                <th>最大步数</th>
                <th>工具调用上限</th>
                <th>其他预算</th>
              </tr>
            </thead>
            <tbody>
              {budgets.map(({ key, budget }) => {
                const extras = Object.entries(budget)
                  .filter(([k]) => !knownBudgetKeys.has(k))
                  .map(([k, v]) => `${EXTRA_BUDGET_LABELS[k] ?? k}: ${String(v)}`);
                return (
                  <tr key={key}>
                    <td>{AGENT_LABELS[key] ?? key}</td>
                    <td>{budget.prompt_version ?? '—'}</td>
                    <td>{budget.max_steps ?? '—'}</td>
                    <td>{budget.max_tool_calls ?? '—'}</td>
                    <td>{extras.length > 0 ? extras.join(' · ') : '—'}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      <div className="card">
        <h3>运行时能力矩阵</h3>
        <div className="cap-grid">
          {Object.entries(config.runtime_capabilities).map(([runtime, caps]) => (
            <div className="cap-card" key={runtime}>
              <div className="cap-title">
                <span className="badge badge-gray">{runtime}</span>
                {runtime === agent.runtime && <span className="badge badge-green">当前</span>}
              </div>
              <div className="kv-list">
                {Object.entries(caps).map(([k, v]) => (
                  <div className="kv-row" key={k}>
                    <span className="kv-key">{k}</span>
                    <span>{formatCapabilityValue(v)}</span>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

/* ===================== 知识索引 ===================== */

function KnowledgeIndexSection() {
  const [index, setIndex] = useState<KnowledgeIndex | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    api
      .get<KnowledgeIndex>('/api/admin/knowledge-index')
      .then((i) => {
        if (alive) setIndex(i);
      })
      .catch((e) => {
        if (alive) setError(errorDetail(e));
      });
    return () => {
      alive = false;
    };
  }, []);

  if (error) return <ErrorBox message={error} />;
  if (index === null) return <Loading label="加载知识索引状态…" />;

  return (
    <div className="admin-sections">
      <div className="card">
        <h3>语义知识索引</h3>
        <div className="kv-list">
          <div className="kv-row">
            <span className="kv-key">检索引擎</span>
            <span>{index.engine}</span>
          </div>
          <div className="kv-row">
            <span className="kv-key">语义版本</span>
            <span>v{index.semantic_version}</span>
          </div>
          <div className="kv-row">
            <span className="kv-key">指标数</span>
            <span>{index.metrics}</span>
          </div>
          <div className="kv-row">
            <span className="kv-key">术语数</span>
            <span>{index.terms}</span>
          </div>
          <div className="kv-row">
            <span className="kv-key">关联规则数</span>
            <span>{index.join_rules}</span>
          </div>
        </div>
        <div className="note-box">{index.note}</div>
      </div>
    </div>
  );
}

/* ===================== 运行列表 ===================== */

function RunsSection() {
  return <RunsList limit={50} />;
}

/* ===================== 评测 ===================== */

const EVAL_STATUS_CLASS: Record<string, string> = {
  passed: 'badge-green',
  failed: 'badge-red',
  error: 'badge-red',
};

const EVAL_STATUS_LABELS: Record<string, string> = {
  passed: '通过',
  failed: '未通过',
  error: '异常',
};

function EvalsSection() {
  const [evals, setEvals] = useState<EvalRunEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<number | null>(null);

  useEffect(() => {
    let alive = true;
    api
      .get<EvalRunEntry[]>('/api/admin/evals')
      .then((r) => {
        if (alive) setEvals(r);
      })
      .catch((e) => {
        if (alive) setError(errorDetail(e));
      });
    return () => {
      alive = false;
    };
  }, []);

  if (error) return <ErrorBox message={error} />;
  if (evals === null) return <Loading label="加载评测记录…" />;

  if (evals.length === 0) {
    return (
      <div className="card empty-state">
        <div className="empty-state-title">暂无评测记录</div>
        <p className="muted">运行评测套件后，结果会出现在这里。</p>
      </div>
    );
  }

  return (
    <div className="evals-list">
      {evals.map((run) => {
        const accuracy =
          typeof run.summary.accuracy === 'number' ? `${(run.summary.accuracy * 100).toFixed(1)}%` : '—';
        const expanded = expandedId === run.id;
        return (
          <div className="card eval-item" key={run.id}>
            <button
              type="button"
              className="eval-head"
              onClick={() => setExpandedId(expanded ? null : run.id)}
            >
              <span className="eval-title">
                #{run.id} · {run.case_set}
              </span>
              <span className="muted">{formatDateTime(run.created_at)}</span>
              <span className="badge badge-blue">
                通过 {run.summary.passed ?? '—'} / {run.summary.total ?? '—'} · 准确率 {accuracy}
              </span>
              <span className="caret" aria-hidden="true">
                {expanded ? '▴' : '▾'}
              </span>
            </button>
            {expanded && (
              <div className="eval-cases">
                <h4>逐用例结果（{run.cases.length}）</h4>
                <div className="eval-case-grid">
                  {run.cases.map((c) => (
                    <span className="eval-case" key={c.case_id}>
                      <span className={`badge ${EVAL_STATUS_CLASS[c.status] ?? 'badge-gray'}`}>
                        {EVAL_STATUS_LABELS[c.status] ?? c.status}
                      </span>
                      {c.case_id}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
