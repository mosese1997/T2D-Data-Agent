import { useMemo } from 'react';
import type { EChartsOption } from 'echarts';
import type { CanvasComponent, CanvasDisplay, RowsResponse } from '../../api/types';
import { useSourceRows } from '../../hooks/useSourceRows';
import { CardSkeleton, ErrorBox } from '../common/ui';
import EChart from './EChart';
import { BRAND_COLOR } from '../../theme';

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

/** 数值与单位分开渲染：大数字 + 小字单位（币种前缀 / 百分比后缀） */
function formatMetricParts(
  raw: unknown,
  display: CanvasDisplay | null | undefined,
): { text: string; prefix: string | null; suffix: string | null } {
  if (raw === null || raw === undefined || raw === '') return { text: '—', prefix: null, suffix: null };
  const n = typeof raw === 'number' ? raw : Number(raw);
  if (!Number.isFinite(n)) return { text: String(raw), prefix: null, suffix: null };
  const unit = display?.unit ?? null;
  const precision = display?.precision ?? (unit === 'currency' ? 2 : 0);
  const text = n.toLocaleString('en-US', {
    minimumFractionDigits: precision,
    maximumFractionDigits: precision,
  });
  if (unit === 'currency') return { text, prefix: '$', suffix: null };
  if (unit === 'percent') return { text, prefix: null, suffix: '%' };
  return { text, prefix: null, suffix: null };
}

/** 日期列名：day / date / dt / 日期 等 */
const DATE_NAME_RE = /(^|_)(day|date|dt|week|month|日期|时间)(_|$)/i;

/** 值形如 YYYY-MM-DD / YYYY-MM 的字符串视为日期 */
function looksLikeDate(v: unknown): boolean {
  return typeof v === 'string' && /^\d{4}-\d{1,2}(-\d{1,2})?/.test(v.trim());
}

function toNumber(v: unknown): number | null {
  if (v === null || v === undefined || v === '') return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

/**
 * 从 source 行里提取迷你趋势序列：要求 ≥3 行、含日期列、指标列可数值化。
 * 没有时间序列数据时返回 null——不硬造趋势。
 */
export function extractSparkSeries(
  rows: RowsResponse,
  field: string | null | undefined,
): { dates: string[]; values: number[] } | null {
  if (!field) return null;
  const fIdx = rows.columns.findIndex((c) => c.name === field);
  if (fIdx < 0) return null;

  // 找日期列：先按列名，再按值形状
  let dIdx = rows.columns.findIndex((c) => DATE_NAME_RE.test(c.name));
  if (dIdx < 0) {
    dIdx = rows.columns.findIndex((c) => rows.rows.some((r) => looksLikeDate(r[rows.columns.indexOf(c)])));
  }
  if (dIdx < 0) return null;

  const points: { d: string; v: number }[] = [];
  for (const row of rows.rows) {
    const d = row[dIdx];
    const v = toNumber(row[fIdx]);
    if (d === null || d === undefined || d === '' || v === null) continue;
    points.push({ d: String(d), v });
  }
  if (points.length < 3) return null;
  points.sort((a, b) => (a.d < b.d ? -1 : a.d > b.d ? 1 : 0));
  return { dates: points.map((p) => p.d), values: points.map((p) => p.v) };
}

/** 无轴线的迷你面积线（品牌橙渐变填充，禁动画） */
function sparklineOption(dates: string[], values: number[]): EChartsOption {
  return {
    animation: false,
    grid: { left: 0, right: 0, top: 3, bottom: 3 },
    xAxis: { type: 'category', show: false, boundaryGap: false, data: dates },
    yAxis: { type: 'value', show: false },
    tooltip: { show: false },
    series: [
      {
        type: 'line',
        data: values,
        showSymbol: false,
        smooth: 0.2,
        lineStyle: { width: 2, color: BRAND_COLOR },
        itemStyle: { color: BRAND_COLOR },
        areaStyle: {
          color: {
            type: 'linear',
            x: 0,
            y: 0,
            x2: 0,
            y2: 1,
            colorStops: [
              { offset: 0, color: 'rgba(240, 116, 31, 0.22)' },
              { offset: 1, color: 'rgba(240, 116, 31, 0)' },
            ],
          },
        },
      },
    ],
  };
}

export default function MetricCard({ comp }: { comp: CanvasComponent }) {
  const { rows, error, loading } = useSourceRows(comp.source_id);

  const raw = useMemo(() => {
    if (!rows || !comp.field) return null;
    const idx = rows.columns.findIndex((c) => c.name === comp.field);
    if (idx < 0) return null;
    return rows.rows[0]?.[idx] ?? null;
  }, [rows, comp.field]);

  const hasValue = raw !== null && raw !== undefined && raw !== '';
  const parts = formatMetricParts(raw, comp.display);

  const spark = useMemo(() => (rows ? extractSparkSeries(rows, comp.field) : null), [rows, comp.field]);
  const sparkOption = useMemo(
    () => (spark ? sparklineOption(spark.dates, spark.values) : null),
    [spark],
  );

  return (
    <div className="card metric-card">
      <div className="metric-label">{comp.title || '指标'}</div>
      {loading ? (
        <CardSkeleton variant="metric" />
      ) : error ? (
        <ErrorBox message={error} />
      ) : (
        <div className="metric-body">
          <div className="metric-value-row">
            {hasValue ? (
              <>
                {parts.prefix ? <span className="metric-unit">{parts.prefix}</span> : null}
                <span className="metric-value">{parts.text}</span>
                {parts.suffix ? <span className="metric-unit">{parts.suffix}</span> : null}
              </>
            ) : (
              <span className="metric-value metric-value-empty">—</span>
            )}
          </div>
          {!hasValue ? <div className="metric-no-data">无数据</div> : null}
          {sparkOption ? (
            <div className="metric-sparkline">
              <EChart option={sparkOption} height={36} />
            </div>
          ) : null}
        </div>
      )}
    </div>
  );
}
