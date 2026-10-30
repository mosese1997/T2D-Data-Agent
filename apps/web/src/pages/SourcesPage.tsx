import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { api } from '../api/client';
import { errorMessage } from '../api/error';
import type { Dashboard, DashboardSummary, RowsResponse, Source } from '../api/types';
import { useI18n } from '../i18n';
import { ErrorBox, Loading, formatCell, formatDateTime } from '../components/common/ui';

export default function SourcesPage() {
  const { workspaceId } = useParams();
  const wid = Number(workspaceId);
  const [sources, setSources] = useState<Source[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const { t } = useI18n();

  useEffect(() => {
    let alive = true;
    setSources(null);
    setError(null);
    setSelectedId(null);
    void (async () => {
      try {
        // 后端没有 sources 列表接口：从当前空间所有看板的画布组件里收集引用的 source_id
        const dashes = await api.get<DashboardSummary[]>(`/api/workspaces/${wid}/dashboards`);
        const ids: string[] = [];
        const seen = new Set<string>();
        for (const d of dashes) {
          const dash = await api.get<Dashboard>(`/api/dashboards/${d.id}`);
          for (const comp of dash.canvas?.components ?? []) {
            if (comp.source_id && !seen.has(comp.source_id)) {
              seen.add(comp.source_id);
              ids.push(comp.source_id);
            }
          }
        }
        const loaded: Source[] = [];
        for (const id of ids) {
          try {
            loaded.push(await api.get<Source>(`/api/sources/${encodeURIComponent(id)}`));
          } catch {
            // 单个 source 拉取失败时跳过
          }
        }
        if (alive) setSources(loaded);
      } catch (e) {
        if (alive) setError(errorMessage(e));
      }
    })();
    return () => {
      alive = false;
    };
  }, [wid]);

  const selected = sources?.find((s) => String(s.id) === selectedId) ?? null;

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>{t('sources.title')}</h1>
          <p className="muted">{t('sources.sub')}</p>
        </div>
      </div>

      {error && <ErrorBox message={error} />}
      {sources === null && !error && <Loading label={t('sources.collecting')} />}

      {sources !== null && (
        <div className="sources-layout">
          <div className="sources-list">
            {sources.map((s) => (
              <button
                type="button"
                key={s.id}
                className={`card source-item ${String(s.id) === selectedId ? 'active' : ''}`}
                onClick={() => setSelectedId(String(s.id))}
              >
                <div className="source-title">{s.title}</div>
                <div className="muted">
                  {t('sources.rowsAt', { n: s.row_count, time: formatDateTime(s.created_at) })}
                </div>
              </button>
            ))}
            {sources.length === 0 && <div className="muted">{t('sources.emptyList')}</div>}
          </div>
          <div className="source-detail">
            {selected ? (
              <SourceDetail source={selected} />
            ) : (
              <div className="muted source-detail-empty">{t('sources.detailEmpty')}</div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function SourceDetail({ source }: { source: Source }) {
  const [preview, setPreview] = useState<RowsResponse | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const { t } = useI18n();

  useEffect(() => {
    let alive = true;
    setPreview(null);
    setPreviewError(null);
    api
      .get<RowsResponse>(`/api/sources/${encodeURIComponent(source.id)}/rows?page=1&size=50`)
      .then((r) => {
        if (alive) setPreview(r);
      })
      .catch((e) => {
        if (alive) setPreviewError(errorMessage(e));
      });
    return () => {
      alive = false;
    };
  }, [source.id]);

  const notes = source.caliber_notes?.notes ?? [];

  return (
    <div className="card source-detail-card">
      <h3 className="source-detail-title">{source.title}</h3>
      <div className="muted">
        {t('sources.detailMeta', { n: source.row_count, status: source.status, time: formatDateTime(source.created_at) })}
      </div>

      <h4>SQL</h4>
      <pre className="sql-block">{source.sql}</pre>

      {notes.length > 0 && (
        <>
          <h4>{t('sources.caliberNotes')}</h4>
          <ul className="notes-list">
            {notes.map((n, i) => (
              <li key={i}>{n}</li>
            ))}
          </ul>
        </>
      )}

      <h4>{t('sources.preview')}</h4>
      {previewError && <ErrorBox message={previewError} />}
      {preview ? (
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                {preview.columns.map((c) => (
                  <th key={c.name}>{c.name}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {preview.rows.map((row, i) => (
                <tr key={i}>
                  {row.map((v, j) => (
                    <td key={j}>{formatCell(v)}</td>
                  ))}
                </tr>
              ))}
              {preview.rows.length === 0 && (
                <tr>
                  <td colSpan={preview.columns.length} className="muted">
                    {t('sources.noRows')}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      ) : (
        !previewError && <Loading label={t('sources.loadingPreview')} />
      )}
    </div>
  );
}
