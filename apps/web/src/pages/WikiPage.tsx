import { useEffect, useState } from 'react';
import { api } from '../api/client';
import { errorDetail } from '../api/error';
import type { MetricEntry, TermEntry, WikiData } from '../api/types';
import { useI18n } from '../i18n';
import { ErrorBox, Loading } from '../components/common/ui';

type WikiTab = 'metrics' | 'terms';

/** 指标字典 + 业务术语（任务书 §13）。任何成员可读（GET /api/admin/wiki）。 */
export default function WikiPage() {
  const [tab, setTab] = useState<WikiTab>('metrics');
  const [data, setData] = useState<WikiData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const { t } = useI18n();

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
          <h1>{t('wiki.title')}</h1>
          <p className="muted">{t('wiki.sub')}</p>
        </div>
      </div>

      <nav className="section-tabs">
        <button
          type="button"
          className={`tab ${tab === 'metrics' ? 'active' : ''}`}
          onClick={() => setTab('metrics')}
        >
          {t('wiki.metrics')}{data ? `（${data.metrics.length}）` : ''}
        </button>
        <button
          type="button"
          className={`tab ${tab === 'terms' ? 'active' : ''}`}
          onClick={() => setTab('terms')}
        >
          {t('wiki.terms')}{data ? `（${data.terms.length}）` : ''}
        </button>
      </nav>

      {error && <ErrorBox message={error} />}
      {data === null && !error && <Loading label={t('wiki.loading')} />}

      {data !== null && tab === 'metrics' && (
        <div className="wiki-grid">
          {data.metrics.map((m) => (
            <MetricCard metric={m} key={m.metric_key} />
          ))}
          {data.metrics.length === 0 && <div className="muted">{t('wiki.noMetrics')}</div>}
        </div>
      )}

      {data !== null && tab === 'terms' && (
        <div className="wiki-grid">
          {data.terms.map((t) => (
            <TermCard term={t} key={t.term} />
          ))}
          {data.terms.length === 0 && <div className="muted">{t('wiki.noTerms')}</div>}
        </div>
      )}
    </div>
  );
}

function asStringList(v: unknown): string[] {
  return Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string') : [];
}

function MetricCard({ metric }: { metric: MetricEntry }) {
  const { t, locale } = useI18n();
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
      <h4>{t('wiki.caliberPoints')}</h4>
      <div className="kv-list">
        <div className="kv-row">
          <span className="kv-key">{t('wiki.baseDataset')}</span>
          <span>{metric.base_dataset ?? '—'}</span>
        </div>
        <div className="kv-row">
          <span className="kv-key">{t('wiki.grain')}</span>
          <span>{metric.grain ? t(`wiki.grain.${metric.grain}`, undefined, metric.grain) : '—'}</span>
        </div>
        <div className="kv-row">
          <span className="kv-key">{t('wiki.currency')}</span>
          <span>
            {metric.currency_policy ? t(`wiki.currency.${metric.currency_policy}`, undefined, metric.currency_policy) : '—'}
          </span>
        </div>
        <div className="kv-row">
          <span className="kv-key">{t('wiki.exclusions')}</span>
          <span>{exclusions.length > 0 ? exclusions.join(locale === 'zh' ? '；' : '; ') : t('wiki.none')}</span>
        </div>
      </div>
    </div>
  );
}

function TermCard({ term }: { term: TermEntry }) {
  const { t } = useI18n();
  const aliases = asStringList(term.aliases);
  return (
    <div className="card wiki-card">
      <div className="wiki-card-head">
        <h3>{term.term}</h3>
        {term.ref_metric && <span className="badge badge-blue">{t('wiki.refMetric', { metric: term.ref_metric })}</span>}
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
