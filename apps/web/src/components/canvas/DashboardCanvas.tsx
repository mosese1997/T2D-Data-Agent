import type { Canvas, CanvasComponent } from '../../api/types';
import MetricCard from './MetricCard';
import ChartCard from './ChartCard';
import DataTableBlock from './DataTableBlock';
import TextBlock from './TextBlock';

export interface DashboardCanvasProps {
  canvas: Canvas | null;
  /** 紧凑模式（用于 Agent 面板里的预览） */
  compact?: boolean;
}

export default function DashboardCanvas({ canvas, compact = false }: DashboardCanvasProps) {
  const components = canvas?.components ?? [];
  const order = canvas?.layout?.order ?? null;
  const cols = canvas?.layout?.grid_cols ?? 12;

  const ordered: CanvasComponent[] = [];
  if (order) {
    for (const id of order) {
      const c = components.find((comp) => comp.id === id);
      if (c) ordered.push(c);
    }
  }
  for (const c of components) {
    if (!ordered.includes(c)) ordered.push(c);
  }

  if (ordered.length === 0) {
    return <div className="canvas-empty">画布为空——在右侧 Agent 面板描述你想看的数据，让 Agent 帮你搭建看板。</div>;
  }

  return (
    <div className="canvas-grid" style={{ gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))` }}>
      {ordered.map((comp) => {
        const span = Math.min(Math.max(comp.span ?? 12, 1), cols);
        return (
          <div key={comp.id} className="canvas-cell" style={{ gridColumn: `span ${span}` }}>
            <ComponentView comp={comp} compact={compact} />
          </div>
        );
      })}
    </div>
  );
}

function ComponentView({ comp, compact }: { comp: CanvasComponent; compact: boolean }) {
  switch (comp.type) {
    case 'metric_card':
      return <MetricCard comp={comp} />;
    case 'line_chart':
    case 'bar_chart':
      return <ChartCard comp={comp} compact={compact} />;
    case 'data_table':
      return <DataTableBlock comp={comp} compact={compact} />;
    case 'text_block':
      return <TextBlock comp={comp} />;
    default:
      return <div className="card comp-unknown">暂不支持的组件类型：{comp.type}</div>;
  }
}
