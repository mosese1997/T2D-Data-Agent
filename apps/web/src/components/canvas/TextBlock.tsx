import type { CanvasComponent } from '../../api/types';

export default function TextBlock({ comp }: { comp: CanvasComponent }) {
  return (
    <div className="card text-block">
      <div className="text-block-content">{comp.content ?? ''}</div>
    </div>
  );
}
