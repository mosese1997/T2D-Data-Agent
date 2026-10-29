import { useHealthStore } from '../../stores/health';

export default function DemoBanner() {
  const demoMode = useHealthStore((s) => s.health?.demo_mode === true);
  if (!demoMode) return null;
  return (
    <div className="demo-banner" role="status">
      演示数据模式——未连接云上数据服务，数据为本地模拟
    </div>
  );
}
