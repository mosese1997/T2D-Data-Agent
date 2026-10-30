import { useHealthStore } from '../../stores/health';
import { useI18n } from '../../i18n';

export default function DemoBanner() {
  const demoMode = useHealthStore((s) => s.health?.demo_mode === true);
  const { t } = useI18n();
  if (!demoMode) return null;
  return (
    <div className="demo-banner" role="status">
      {t('demo.banner')}
    </div>
  );
}
