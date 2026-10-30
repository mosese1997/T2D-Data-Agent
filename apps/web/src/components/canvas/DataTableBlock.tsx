import { useEffect, useMemo, useState } from 'react';
import type { CanvasComponent, RowsResponse } from '../../api/types';
import { useSourceRows } from '../../hooks/useSourceRows';
import { useI18n } from '../../i18n';
import { CardSkeleton, EmptyState, ErrorBox, formatCell } from '../common/ui';

/** 判断某列是否为数字列（采样前 50 行的非空值全部可数值化即认定） */
function isNumericColumn(rows: RowsResponse, idx: number): boolean {
  let seen = 0;
  for (const row of rows.rows.slice(0, 50)) {
    const v = row[idx];
    if (v === null || v === undefined || v === '') continue;
    if (typeof v === 'number') {
      seen++;
      continue;
    }
    if (typeof v === 'string' && v.trim() !== '' && Number.isFinite(Number(v))) {
      seen++;
      continue;
    }
    return false; // 出现非数字内容
  }
  return seen > 0;
}

export default function DataTableBlock({ comp, compact = false }: { comp: CanvasComponent; compact?: boolean }) {
  const { rows, error, loading } = useSourceRows(comp.source_id);
  const { t } = useI18n();
  const [page, setPage] = useState(1);
  const pageSize = (compact ? Math.min(comp.display?.page_size ?? 10, 10) : comp.display?.page_size) ?? 20;

  useEffect(() => {
    setPage(1);
  }, [comp.id, pageSize]);

  const numericIdxs = useMemo(() => {
    if (!rows) return new Set<number>();
    const s = new Set<number>();
    rows.columns.forEach((_c, idx) => {
      if (isNumericColumn(rows, idx)) s.add(idx);
    });
    return s;
  }, [rows]);

  let body: React.ReactNode;
  if (loading) {
    body = <CardSkeleton variant="table" />;
  } else if (error) {
    body = <ErrorBox message={error} />;
  } else if (!rows) {
    body = <EmptyState />;
  } else {
    const wanted = (comp.columns ?? []).filter((name) => rows.columns.some((rc) => rc.name === name));
    const colNames = wanted.length > 0 ? wanted : rows.columns.map((c) => c.name);
    const idxs = colNames.map((n) => rows.columns.findIndex((c) => c.name === n));
    const total = rows.rows.length;
    const totalPages = Math.max(1, Math.ceil(total / pageSize));
    const safePage = Math.min(page, totalPages);
    const slice = rows.rows.slice((safePage - 1) * pageSize, safePage * pageSize);

    body = (
      <>
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                {idxs.map((idx, j) => (
                  <th key={colNames[j]} className={numericIdxs.has(idx) ? 'cell-num' : undefined}>
                    {colNames[j]}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {slice.map((row, i) => (
                <tr key={i}>
                  {idxs.map((idx, j) => (
                    <td key={j} className={numericIdxs.has(idx) ? 'cell-num' : undefined}>
                      {formatCell(row[idx])}
                    </td>
                  ))}
                </tr>
              ))}
              {slice.length === 0 && (
                <tr>
                  <td colSpan={colNames.length}>
                    <EmptyState />
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        <div className="table-footer">
          <span className="muted">{t('table.totalRows', { n: rows.row_count })}</span>
          <span className="table-pager">
            <button type="button" className="btn btn-ghost btn-sm" disabled={safePage <= 1} onClick={() => setPage(safePage - 1)}>
              {t('table.prevPage')}
            </button>
            <span className="muted">
              {t('table.pageIndicator', { page: safePage, total: totalPages })}
            </span>
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              disabled={safePage >= totalPages}
              onClick={() => setPage(safePage + 1)}
            >
              {t('table.nextPage')}
            </button>
          </span>
        </div>
      </>
    );
  }

  return (
    <div className="card data-table-card">
      {comp.title ? (
        <div className="card-head">
          <div className="card-head-title">{comp.title}</div>
          {rows && !loading ? <div className="card-head-meta">{t('common.rows', { n: rows.row_count })}</div> : null}
        </div>
      ) : null}
      {body}
    </div>
  );
}
