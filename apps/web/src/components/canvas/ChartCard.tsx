import { useMemo } from 'react';
import type { EChartsOption } from 'echarts';
import type { CanvasComponent, RowsResponse } from '../../api/types';
import { useSourceRows } from '../../hooks/useSourceRows';
import { ErrorBox, Loading } from '../common/ui';
import EChart from './EChart';

function toNumber(v: unknown): number | null {
  if (v === null || v === undefined || v === '') return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

export function buildChartOption(comp: CanvasComponent, rows: RowsResponse): EChartsOption | null {
  const xField = comp.x?.field;
  if (!xField) return null;
  const xIdx = rows.columns.findIndex((c) => c.name === xField);
  if (xIdx < 0) return null;

  const seriesDefs = (comp.series ?? []).filter((s) => s.field);
  if (seriesDefs.length === 0) return null;

  // 横轴取值：按首次出现顺序去重（split_by 时不同系列可能有不同的 x 集合，取并集）
  const xValues: string[] = [];
  const xSeen = new Set<string>();
  for (const row of rows.rows) {
    const xv = String(row[xIdx] ?? '');
    if (!xSeen.has(xv)) {
      xSeen.add(xv);
      xValues.push(xv);
    }
  }

  // seriesName -> (xValue -> 数值)
  const groups = new Map<string, Map<string, number | null>>();
  const addTo = (name: string, xv: string, val: number | null) => {
    let m = groups.get(name);
    if (!m) {
      m = new Map();
      groups.set(name, m);
    }
    m.set(xv, val);
  };

  for (const def of seriesDefs) {
    const fIdx = rows.columns.findIndex((c) => c.name === def.field);
    if (fIdx < 0) continue;
    if (def.split_by) {
      const sIdx = rows.columns.findIndex((c) => c.name === def.split_by);
      if (sIdx < 0) continue;
      for (const row of rows.rows) {
        const sname = String(row[sIdx] ?? def.split_by);
        addTo(sname, String(row[xIdx] ?? ''), toNumber(row[fIdx]));
      }
    } else {
      const sname = def.name ?? def.field;
      for (const row of rows.rows) {
        addTo(sname, String(row[xIdx] ?? ''), toNumber(row[fIdx]));
      }
    }
  }
  if (groups.size === 0) return null;

  const stacked = comp.display?.stacked === true;
  const chartType = comp.type === 'bar_chart' ? 'bar' : 'line';

  const option: EChartsOption = {
    animation: true,
    tooltip: { trigger: 'axis' },
    legend: comp.display?.legend === false ? undefined : { bottom: 0, type: 'scroll' },
    grid: { left: 8, right: 16, top: 24, bottom: 36, containLabel: true },
    xAxis: { type: 'category', data: xValues },
    yAxis: { type: 'value' },
    series: Array.from(groups.entries()).map(([name, m]) => ({
      name,
      type: chartType,
      data: xValues.map((xv) => (m.has(xv) ? (m.get(xv) as number | null) : null)),
      stack: stacked ? 'total' : undefined,
      emphasis: { focus: 'series' },
    })),
  };
  return option;
}

export default function ChartCard({ comp, compact = false }: { comp: CanvasComponent; compact?: boolean }) {
  const { rows, error, loading } = useSourceRows(comp.source_id);
  const option = useMemo(() => (rows ? buildChartOption(comp, rows) : null), [comp, rows]);

  return (
    <div className="card chart-card">
      {comp.title ? <div className="card-title">{comp.title}</div> : null}
      {loading ? (
        <Loading label="取数中…" />
      ) : error ? (
        <ErrorBox message={error} />
      ) : option ? (
        <EChart option={option} height={compact ? 180 : 300} />
      ) : (
        <div className="muted chart-no-data">图表配置缺少可用的字段，无法渲染。</div>
      )}
    </div>
  );
}
