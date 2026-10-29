import type { ReactNode } from 'react';

export function Loading({ label = '加载中…' }: { label?: string }) {
  return (
    <div className="loading">
      <span className="spinner" aria-hidden="true" />
      <span>{label}</span>
    </div>
  );
}

export function ErrorBox({ message, children }: { message?: string | null; children?: ReactNode }) {
  return <div className="error-box">{children ?? message}</div>;
}

const STATUS_LABELS: Record<string, string> = {
  draft: '草稿',
  published: '已发布',
  archived: '已归档',
  queued: '排队中',
  running: '运行中',
  waiting_for_user: '等待补充信息',
  waiting_for_apply: '待应用',
  succeeded: '已完成',
  failed: '失败',
  cancelled: '已取消',
  interrupted: '已中断',
};

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
  return <span className={`badge ${STATUS_CLASS[status] ?? 'badge-gray'}`}>{STATUS_LABELS[status] ?? status}</span>;
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
  return <span className={`badge ${RUN_STATUS_CLASS[status] ?? 'badge-gray'}`}>{STATUS_LABELS[status] ?? status}</span>;
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
  return d.toLocaleString('zh-CN', { hour12: false });
}

export function relativeTime(at: number): string {
  const diff = Date.now() - at;
  const minutes = Math.floor(diff / 60_000);
  if (minutes < 1) return '刚刚';
  if (minutes < 60) return `${minutes} 分钟前`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} 小时前`;
  const days = Math.floor(hours / 24);
  return `${days} 天前`;
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
