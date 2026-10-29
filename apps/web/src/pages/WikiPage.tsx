import { useEffect, useState } from 'react';
import { api } from '../api/client';
import { errorDetail } from '../api/error';
import type { MetricEntry, TermEntry, WikiData } from '../api/types';
import { ErrorBox, Loading } from '../components/common/ui';

type WikiTab = 'metrics' | 'terms';

/** 指标字典 + 业务术语（任务书 §13）。任何成员可读（GET /api/admin/wiki）。 */
export default function WikiPage() {
  const [tab, setTab] = useState<WikiTab>('metrics');
  const [data, setData] = useState<WikiData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    api
      .get<WikiData>('/api/admin/wiki')
      .then((d) => {
        if (alive) setData(d);
      })
      .catch((e) => {
        if (alive) setError(errorDetail(e));
      });
    return () => {
      alive = false;
    };
  }, []);

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Wiki · 指标字典与业务术语</h1>
          <p className="muted">语义层的权威口径定义。Agent 生成查询时以此为准，相似度检索不决定口径与权限。</p>
        </div>
      </div>

      <nav className="section-tabs">
        <button
          type="button"
          className={`tab ${tab === 'metrics' ? 'active' : ''}`}
          onClick={() => setTab('metrics')}
        >
          指标字典{data ? `（${data.metrics.length}）` : ''}
        </button>
        <button
          type="button"
          className={`tab ${tab === 'terms' ? 'active' : ''}`}
          onClick={() => setTab('terms')}
        >
          业务术语{data ? `（${data.terms.length}）` : ''}
        </button>
      </nav>

      {error && <ErrorBox message={error} />}
      {data === null && !error && <Loading label="加载语义字典…" />}

      {data !== null && tab === 'metrics' && (
        <div className="wiki-grid">
          {data.metrics.map((m) => (
            <MetricCard metric={m} key={m.metric_key} />
          ))}
          {data.metrics.length === 0 && <div className="muted">暂无指标定义。</div>}
        </div>
      )}

      {data !== null && tab === 'terms' && (
        <div className="wiki-grid">
          {data.terms.map((t) => (
            <TermCard term={t} key={t.term} />
          ))}
          {data.terms.length === 0 && <div className="muted">暂无业务术语。</div>}
        </div>
      )}
    </div>
  );
}

const CURRENCY_LABELS: Record<string, string> = {
  local: '本币（local）',
  usd_fixed: '固定 USD（usd_fixed）',
};

const GRAIN_LABELS: Record<string, string> = {
  order: '订单（order）',
  item: '订单行（item）',
  day: '天（day）',
};

function asStringList(v: unknown): string[] {
  return Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string') : [];
}

function MetricCard({ metric }: { metric: MetricEntry }) {
  const synonyms = asStringList(metric.synonyms);
  const exclusions = asStringList(metric.exclusions);
  return (
    <div className="card wiki-card">
      <div className="wiki-card-head">
        <h3>{metric.name}</h3>
        <span className="badge badge-gray">v{metric.version ?? '—'}</span>
      </div>
      <div className="wiki-card-key">{metric.metric_key}</div>
      {synonyms.length > 0 && (
        <div className="tag-row">
          {synonyms.map((s) => (
            <span className="tag" key={s}>
              {s}
            </span>
          ))}
        </div>
      )}
      <p>{metric.description}</p>
      <h4>口径要点</h4>
      <div className="kv-list">
        <div className="kv-row">
          <span className="kv-key">基础数据集</span>
          <span>{metric.base_dataset ?? '—'}</span>
        </div>
        <div className="kv-row">
          <span className="kv-key">统计粒度</span>
          <span>{metric.grain ? (GRAIN_LABELS[metric.grain] ?? metric.grain) : '—'}</span>
        </div>
        <div className="kv-row">
          <span className="kv-key">币种策略</span>
          <span>
            {metric.currency_policy ? (CURRENCY_LABELS[metric.currency_policy] ?? metric.currency_policy) : '—'}
          </span>
        </div>
        <div className="kv-row">
          <span className="kv-key">排除条件</span>
          <span>{exclusions.length > 0 ? exclusions.join('；') : '无'}</span>
        </div>
      </div>
    </div>
  );
}

function TermCard({ term }: { term: TermEntry }) {
  const aliases = asStringList(term.aliases);
  return (
    <div className="card wiki-card">
      <div className="wiki-card-head">
        <h3>{term.term}</h3>
        {term.ref_metric && <span className="badge badge-blue">关联指标：{term.ref_metric}</span>}
      </div>
      {aliases.length > 0 && (
        <div className="tag-row">
          {aliases.map((a) => (
            <span className="tag" key={a}>
              {a}
            </span>
          ))}
        </div>
      )}
      <p>{term.definition}</p>
    </div>
  );
}
