import { useEffect, useState } from 'react';
import type { CanvasComponent } from '../../api/types';
import { useSourceRows } from '../../hooks/useSourceRows';
import { ErrorBox, Loading, formatCell } from '../common/ui';

export default function DataTableBlock({ comp, compact = false }: { comp: CanvasComponent; compact?: boolean }) {
  const { rows, error, loading } = useSourceRows(comp.source_id);
  const [page, setPage] = useState(1);
  const pageSize = (compact ? Math.min(comp.display?.page_size ?? 10, 10) : comp.display?.page_size) ?? 20;

  useEffect(() => {
    setPage(1);
  }, [comp.id, pageSize]);

  let body: React.ReactNode;
  if (loading) {
    body = <Loading label="取数中…" />;
  } else if (error) {
    body = <ErrorBox message={error} />;
  } else if (!rows) {
    body = <div className="muted">暂无数据</div>;
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
                {colNames.map((n) => (
                  <th key={n}>{n}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {slice.map((row, i) => (
                <tr key={i}>
                  {idxs.map((idx, j) => (
                    <td key={j}>{formatCell(row[idx])}</td>
                  ))}
                </tr>
              ))}
              {slice.length === 0 && (
                <tr>
                  <td colSpan={colNames.length} className="muted">
                    无数据行
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        <div className="table-footer">
          <span className="muted">共 {rows.row_count} 行</span>
          <span className="table-pager">
            <button type="button" className="btn btn-ghost btn-sm" disabled={safePage <= 1} onClick={() => setPage(safePage - 1)}>
              上一页
            </button>
            <span className="muted">
              第 {safePage} / {totalPages} 页
            </span>
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              disabled={safePage >= totalPages}
              onClick={() => setPage(safePage + 1)}
            >
              下一页
            </button>
          </span>
        </div>
      </>
    );
  }

  return (
    <div className="card data-table-card">
      {comp.title ? <div className="card-title">{comp.title}</div> : null}
      {body}
    </div>
  );
}
