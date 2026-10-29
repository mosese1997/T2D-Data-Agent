import type { CanvasComponent, CanvasDisplay } from '../../api/types';
import { useSourceRows } from '../../hooks/useSourceRows';
import { ErrorBox, Loading } from '../common/ui';

export function formatMetricValue(raw: unknown, display: CanvasDisplay | null | undefined): string {
  if (raw === null || raw === undefined || raw === '') return '—';
  const n = typeof raw === 'number' ? raw : Number(raw);
  if (!Number.isFinite(n)) return String(raw);
  const unit = display?.unit ?? null;
  const precision = display?.precision ?? (unit === 'currency' ? 2 : 0);
  const formatted = n.toLocaleString('en-US', {
    minimumFractionDigits: precision,
    maximumFractionDigits: precision,
  });
  if (unit === 'currency') return `$${formatted}`;
  if (unit === 'percent') return `${formatted}%`;
  return formatted;
}

export default function MetricCard({ comp }: { comp: CanvasComponent }) {
  const { rows, error, loading } = useSourceRows(comp.source_id);

  let value = '—';
  if (rows && comp.field) {
    const idx = rows.columns.findIndex((c) => c.name === comp.field);
    if (idx >= 0) {
      const raw = rows.rows[0]?.[idx];
      value = formatMetricValue(raw, comp.display);
    }
  }

  return (
    <div className="card metric-card">
      <div className="metric-title">{comp.title || '指标'}</div>
      {loading ? (
        <Loading label="取数中…" />
      ) : error ? (
        <ErrorBox message={error} />
      ) : (
        <div className="metric-value">{value}</div>
      )}
    </div>
  );
}
