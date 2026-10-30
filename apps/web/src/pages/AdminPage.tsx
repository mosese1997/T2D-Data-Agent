import { useEffect, useState } from 'react';
import { Navigate } from 'react-router-dom';
import { api } from '../api/client';
import { errorDetail } from '../api/error';
import type { AgentBudget, AgentConfigResponse, EvalRunEntry, KnowledgeIndex } from '../api/types';
import RunsList from '../components/admin/RunsList';
import { useI18n, tr } from '../i18n';
import { ErrorBox, Loading, formatDateTime } from '../components/common/ui';
import { useIsAdmin } from '../hooks/useIsAdmin';

type AdminTab = 'config' | 'knowledge' | 'runs' | 'evals';

/** 管理台（任务书 §13）：仅管理员可见，非管理员重定向到活动页（那里有权限提示）。 */
export default function AdminPage() {
  const isAdmin = useIsAdmin();
  const [tab, setTab] = useState<AdminTab>('config');
  const { t } = useI18n();

  const TABS: { key: AdminTab; label: string }[] = [
    { key: 'config', label: t('admin.tab.config') },
    { key: 'knowledge', label: t('admin.tab.knowledge') },
    { key: 'runs', label: t('admin.tab.runs') },
    { key: 'evals', label: t('admin.tab.evals') },
  ];

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
          <h1>{t('admin.title')}</h1>
          <p className="muted">{t('admin.sub')}</p>
        </div>
      </div>

      <nav className="section-tabs">
        {TABS.map((tabItem) => (
          <button
            type="button"
            key={tabItem.key}
            className={`tab ${tab === tabItem.key ? 'active' : ''}`}
            onClick={() => setTab(tabItem.key)}
          >
            {tabItem.label}
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

function formatCapabilityValue(v: unknown): string {
  if (typeof v === 'boolean') return v ? tr('admin.capability.yes') : tr('admin.capability.no');
  return String(v);
}

function AgentConfigSection() {
  const { t } = useI18n();
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
      setSwitchDone(t('admin.runtimeSwitched', { runtime }));
      load();
    } catch (e) {
      // 后端会拒绝未接入的 runtime（409），如实展示原因
      setSwitchError(errorDetail(e));
    } finally {
      setSwitching(null);
    }
  };

  if (error) return <ErrorBox message={error} />;
  if (config === null) return <Loading label={t('admin.loadingConfig')} />;

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
        <h3>{t('admin.currentRuntime')}</h3>
        <div className="kv-list">
          <div className="kv-row">
            <span className="kv-key">runtime</span>
            <span>
              <span className="badge badge-blue">{agent.runtime}</span>
            </span>
          </div>
          <div className="kv-row">
            <span className="kv-key">{t('admin.model')}</span>
            <span>{agent.model}</span>
          </div>
          <div className="kv-row">
            <span className="kv-key">{t('admin.sampling')}</span>
            <span>
              temperature {agent.temperature ?? '—'} · max_tokens {agent.max_tokens ?? '—'}
            </span>
          </div>
        </div>

        <h4>{t('admin.runtimeSwitch')}</h4>
        <div className="runtime-switch">
          <button
            type="button"
            className="btn btn-primary btn-sm"
            disabled={switching !== null || agent.runtime === 'toolloop'}
            onClick={() => void switchRuntime('toolloop')}
          >
            {agent.runtime === 'toolloop' ? t('admin.runtimeCurrent', { runtime: 'toolloop' }) : t('admin.runtimeSwitchTo', { runtime: 'toolloop' })}
          </button>
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            disabled={switching !== null || agent.runtime === 'swarmflow'}
            onClick={() => void switchRuntime('swarmflow')}
          >
            {agent.runtime === 'swarmflow' ? t('admin.runtimeCurrent', { runtime: 'swarmflow' }) : t('admin.runtimeSwitchTo', { runtime: 'swarmflow' })}
          </button>
          <span className="muted">{t('admin.swarmflowNote')}</span>
        </div>
        {switching !== null && <Loading label={t('admin.switching')} />}
        {switchError && <ErrorBox message={switchError} />}
        {switchDone && <div className="result-box">{switchDone}</div>}
      </div>

      <div className="card">
        <h3>{t('admin.budgets')}</h3>
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th>{t('admin.th.agent')}</th>
                <th>{t('admin.th.promptVersion')}</th>
                <th>{t('admin.th.maxSteps')}</th>
                <th>{t('admin.th.maxToolCalls')}</th>
                <th>{t('admin.th.otherBudgets')}</th>
              </tr>
            </thead>
            <tbody>
              {budgets.map(({ key, budget }) => {
                const extras = Object.entries(budget)
                  .filter(([k]) => !knownBudgetKeys.has(k))
                  .map(([k, v]) => `${t(`admin.budget.${k}`, undefined, k)}: ${String(v)}`);
                return (
                  <tr key={key}>
                    <td>{t(`admin.agent.${key}`, undefined, key)}</td>
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
        <h3>{t('admin.capabilities')}</h3>
        <div className="cap-grid">
          {Object.entries(config.runtime_capabilities).map(([runtime, caps]) => (
            <div className="cap-card" key={runtime}>
              <div className="cap-title">
                <span className="badge badge-gray">{runtime}</span>
                {runtime === agent.runtime && <span className="badge badge-green">{t('admin.current')}</span>}
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
  const { t } = useI18n();
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
  if (index === null) return <Loading label={t('admin.knowledge.loading')} />;

  return (
    <div className="admin-sections">
      <div className="card">
        <h3>{t('admin.knowledge.title')}</h3>
        <div className="kv-list">
          <div className="kv-row">
            <span className="kv-key">{t('admin.knowledge.engine')}</span>
            <span>{index.engine}</span>
          </div>
          <div className="kv-row">
            <span className="kv-key">{t('admin.knowledge.semanticVersion')}</span>
            <span>v{index.semantic_version}</span>
          </div>
          <div className="kv-row">
            <span className="kv-key">{t('admin.knowledge.metrics')}</span>
            <span>{index.metrics}</span>
          </div>
          <div className="kv-row">
            <span className="kv-key">{t('admin.knowledge.terms')}</span>
            <span>{index.terms}</span>
          </div>
          <div className="kv-row">
            <span className="kv-key">{t('admin.knowledge.joinRules')}</span>
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

function EvalsSection() {
  const { t } = useI18n();
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
  if (evals === null) return <Loading label={t('admin.evals.loading')} />;

  if (evals.length === 0) {
    return (
      <div className="card empty-state">
        <div className="empty-state-title">{t('admin.evals.empty.title')}</div>
        <p className="muted">{t('admin.evals.empty.body')}</p>
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
                {t('admin.evals.summary', { passed: run.summary.passed ?? '—', total: run.summary.total ?? '—', accuracy })}
              </span>
              <span className="caret" aria-hidden="true">
                {expanded ? '▴' : '▾'}
              </span>
            </button>
            {expanded && (
              <div className="eval-cases">
                <h4>{t('admin.evals.cases', { n: run.cases.length })}</h4>
                <div className="eval-case-grid">
                  {run.cases.map((c) => (
                    <span className="eval-case" key={c.case_id}>
                      <span className={`badge ${EVAL_STATUS_CLASS[c.status] ?? 'badge-gray'}`}>
                        {t(`admin.eval.${c.status}`, undefined, c.status)}
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
