import type { ReactNode } from 'react';
import { useI18n, getLocale, tr } from '../../i18n';

export function Loading({ label }: { label?: string }) {
  const { t } = useI18n();
  return (
    <div className="loading">
      <span className="spinner" aria-hidden="true" />
      <span>{label ?? t('common.loading')}</span>
    </div>
  );
}

export function ErrorBox({ message, children }: { message?: string | null; children?: ReactNode }) {
  return <div className="error-box">{children ?? message}</div>;
}

/** 骨架屏基础块：浅橙 shimmer 动画（见 global.css .skeleton） */
export function Skeleton({ className = '', style }: { className?: string; style?: React.CSSProperties }) {
  return <div className={`skeleton ${className}`} style={style} aria-hidden="true" />;
}

/** 卡片形状的加载骨架：metric / chart / table 三种变体 */
export function CardSkeleton({ variant }: { variant: 'metric' | 'chart' | 'table' }) {
  if (variant === 'metric') {
    return (
      <div className="skeleton-card" aria-hidden="true">
        <Skeleton className="skeleton-line" style={{ width: '42%', height: 10 }} />
        <Skeleton className="skeleton-line" style={{ width: '58%', height: 24 }} />
        <Skeleton className="skeleton-line" style={{ width: '100%', height: 36 }} />
      </div>
    );
  }
  if (variant === 'chart') {
    return (
      <div className="skeleton-card" aria-hidden="true">
        <Skeleton className="skeleton-line" style={{ width: '36%', height: 12 }} />
        <Skeleton style={{ width: '100%', height: '82%', minHeight: 140 }} />
      </div>
    );
  }
  return (
    <div className="skeleton-card" aria-hidden="true">
      <Skeleton className="skeleton-line" style={{ width: '36%', height: 12 }} />
      <Skeleton className="skeleton-line" style={{ width: '100%', height: 28 }} />
      <Skeleton className="skeleton-line" style={{ width: '100%', height: 28 }} />
      <Skeleton className="skeleton-line" style={{ width: '92%', height: 28 }} />
      <Skeleton className="skeleton-line" style={{ width: '96%', height: 28 }} />
    </div>
  );
}

/** 居中可爱空态：🍊 + 主文案 + 小灰字解释 */
export function EmptyState({
  title,
  hint,
}: {
  title?: string;
  hint?: ReactNode;
}) {
  const { t } = useI18n();
  return (
    <div className="empty-state-cute">
      <div className="empty-state-emoji" aria-hidden="true">
        🍊
      </div>
      <div className="empty-state-title">{title ?? t('empty.noData')}</div>
      {hint ? <div className="empty-state-hint">{hint}</div> : null}
    </div>
  );
}

const STATUS_CLASS: Record<string, string> = {
  draft: 'badge-gray',
  published: 'badge-green',
  archived: 'badge-gray',
  queued: 'badge-blue',
  running: 'badge-blue',
  waiting_for_user: 'badge-orange',
  waiting_for_apply: 'badge-orange',
  succeeded: 'badge-green',
  failed: 'badge-red',
  cancelled: 'badge-gray',
  interrupted: 'badge-gray',
};

export function StatusBadge({ status }: { status: string }) {
  const { t } = useI18n(); // 订阅语言变化，切换即时生效
  return <span className={`badge ${STATUS_CLASS[status] ?? 'badge-gray'}`}>{t(`status.${status}`, undefined, status)}</span>;
}

/** 任务运行状态配色：succeeded 绿 / failed 红 / queued 灰 / running 蓝 / waiting_* 黄 */
const RUN_STATUS_CLASS: Record<string, string> = {
  succeeded: 'badge-green',
  failed: 'badge-red',
  queued: 'badge-gray',
  running: 'badge-blue',
  waiting_for_user: 'badge-orange',
  waiting_for_apply: 'badge-orange',
  cancelled: 'badge-gray',
  interrupted: 'badge-gray',
};

export function RunStatusBadge({ status }: { status: string }) {
  const { t } = useI18n(); // 订阅语言变化，切换即时生效
  return <span className={`badge ${RUN_STATUS_CLASS[status] ?? 'badge-gray'}`}>{t(`status.${status}`, undefined, status)}</span>;
}

/** JSON 美化打印；无法序列化时退化为 String() */
export function prettyJson(v: unknown): string {
  if (v === null || v === undefined) return '—';
  try {
    return JSON.stringify(v, null, 2);
  } catch {
    return String(v);
  }
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(getLocale() === 'zh' ? 'zh-CN' : 'en-US', { hour12: false });
}

export function relativeTime(at: number): string {
  const diff = Date.now() - at;
  const minutes = Math.floor(diff / 60_000);
  if (minutes < 1) return tr('time.justNow');
  if (minutes < 60) return tr('time.minutesAgo', { n: minutes });
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return tr('time.hoursAgo', { n: hours });
  const days = Math.floor(hours / 24);
  return tr('time.daysAgo', { n: days });
}

/** 表格单元格展示：数字做千分位，空值显示 — */
export function formatCell(v: unknown): string {
  if (v === null || v === undefined || v === '') return '—';
  if (typeof v === 'number') return v.toLocaleString('en-US', { maximumFractionDigits: 2 });
  if (typeof v === 'string' && v.trim() !== '' && Number.isFinite(Number(v))) {
    return Number(v).toLocaleString('en-US', { maximumFractionDigits: 2 });
  }
  return String(v);
}
