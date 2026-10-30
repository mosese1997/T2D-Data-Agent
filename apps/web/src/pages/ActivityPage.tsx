import { Loading } from '../components/common/ui';
import RunsList from '../components/admin/RunsList';
import { useIsAdmin } from '../hooks/useIsAdmin';
import { useI18n } from '../i18n';

/**
 * 任务运行活动（任务书 §13）：完整的运行列表接口仅对管理员开放；
 * 普通成员没有任务列表端点，如实提示，不展示任何伪造记录。
 */
export default function ActivityPage() {
  const isAdmin = useIsAdmin();
  const { t } = useI18n();

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>{t('activity.title')}</h1>
          <p className="muted">{t('activity.sub')}</p>
        </div>
      </div>

      {isAdmin === null && <Loading label={t('activity.checkingPermission')} />}

      {isAdmin === false && (
        <div className="card empty-state">
          <div className="empty-state-title">{t('activity.adminOnly.title')}</div>
          <p className="muted">{t('activity.adminOnly.body')}</p>
        </div>
      )}

      {isAdmin === true && <RunsList limit={50} />}
    </div>
  );
}
