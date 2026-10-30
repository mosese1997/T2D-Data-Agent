import { useMemo } from 'react';
import type { EChartsOption } from 'echarts';
import type { CanvasComponent, RowsResponse } from '../../api/types';
import { useSourceRows } from '../../hooks/useSourceRows';
import { useI18n } from '../../i18n';
import { CardSkeleton, EmptyState, ErrorBox } from '../common/ui';
import EChart from './EChart';
import { BRAND_COLOR, CHART_BORDER, CHART_GRID, CHART_MUTED } from '../../theme';

function toNumber(v: unknown): number | null {
  if (v === null || v === undefined || v === '') return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

/** 品牌橙渐变面积（仅单系列折线使用）：12% → 0 透明度 */
function brandAreaGradient() {
  return {
    type: 'linear' as const,
    x: 0,
    y: 0,
    x2: 0,
    y2: 1,
    colorStops: [
      { offset: 0, color: 'rgba(240, 116, 31, 0.12)' },
      { offset: 1, color: 'rgba(240, 116, 31, 0)' },
    ],
  };
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
  const isBar = comp.type === 'bar_chart';
  const singleSeries = groups.size === 1;

  const option: EChartsOption = {
    animation: true,
    tooltip: {
      trigger: 'axis',
      ...(isBar
        ? {}
        : {
            axisPointer: {
              type: 'cross',
              lineStyle: { color: CHART_BORDER, width: 1 },
              crossStyle: { color: CHART_BORDER },
              label: { backgroundColor: '#fdeedd', color: CHART_MUTED, fontSize: 11 },
            },
          }),
    },
    // 图例：小圆点 + 灰字，顶部右侧；单系列不需要图例
    legend:
      singleSeries || comp.display?.legend === false
        ? undefined
        : {
            top: 0,
            right: 0,
            icon: 'circle',
            itemWidth: 8,
            itemHeight: 8,
            itemGap: 14,
            textStyle: { color: CHART_MUTED, fontSize: 11 },
          },
    grid: { left: 8, right: 16, top: 36, bottom: 8, containLabel: true },
    xAxis: {
      type: 'category',
      data: xValues,
      axisLine: { lineStyle: { color: CHART_BORDER } },
      axisTick: { show: false },
      axisLabel: { color: CHART_MUTED, fontSize: 11 },
    },
    yAxis: {
      type: 'value',
      splitLine: { lineStyle: { color: CHART_GRID, width: 1 } },
      axisLabel: { color: CHART_MUTED, fontSize: 11 },
    },
    series: Array.from(groups.entries()).map(([name, m]) => {
      const data = xValues.map((xv) => (m.has(xv) ? (m.get(xv) as number | null) : null));
      if (isBar) {
        return {
          name,
          type: 'bar' as const,
          data,
          stack: stacked ? 'total' : undefined,
          // 柱端 4px 圆角；柱宽自适应但不超过 36px
          barMaxWidth: 36,
          itemStyle: { borderRadius: [4, 4, 0, 0] as [number, number, number, number] },
          emphasis: { focus: 'series' as const },
        };
      }
      return {
        name,
        type: 'line' as const,
        data,
        stack: stacked ? 'total' : undefined,
        smooth: 0.2,
        lineStyle: { width: 2 },
        symbolSize: 5,
        symbol: 'circle',
        // 仅单系列加品牌橙渐变面积；多系列保持纯线
        color: singleSeries ? BRAND_COLOR : undefined,
        areaStyle: singleSeries ? { color: brandAreaGradient() } : undefined,
        emphasis: { focus: 'series' as const },
      };
    }),
  };
  return option;
}

export default function ChartCard({ comp, compact = false }: { comp: CanvasComponent; compact?: boolean }) {
  const { rows, error, loading } = useSourceRows(comp.source_id);
  const { t } = useI18n();
  const option = useMemo(() => (rows ? buildChartOption(comp, rows) : null), [comp, rows]);

  const empty = rows && rows.rows.length === 0;

  return (
    <div className="card chart-card">
      {comp.title ? (
        <div className="card-head">
          <div className="card-head-title">{comp.title}</div>
          {rows && !loading ? <div className="card-head-meta">{t('common.rows', { n: rows.row_count })}</div> : null}
        </div>
      ) : null}
      {loading ? (
        <CardSkeleton variant="chart" />
      ) : error ? (
        <ErrorBox message={error} />
      ) : empty ? (
        <EmptyState hint={t('chart.emptyHint')} />
      ) : option ? (
        <EChart option={option} height={compact ? 180 : 300} />
      ) : (
        <EmptyState hint={t('chart.invalidHint')} />
      )}
    </div>
  );
}
