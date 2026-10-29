export interface RecentEntry {
  workspaceId: number;
  workspaceName: string;
  dashboardId: number;
  title: string;
  at: number;
}

const STORAGE_KEY = 't2d.recent';
const MAX_ENTRIES = 12;

export function getRecent(): RecentEntry[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as RecentEntry[];
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(
      (e) => typeof e.dashboardId === 'number' && typeof e.workspaceId === 'number' && typeof e.title === 'string',
    );
  } catch {
    return [];
  }
}

export function recordRecent(entry: { workspaceId: number; workspaceName: string; dashboardId: number; title: string }): void {
  const list = getRecent().filter((e) => e.dashboardId !== entry.dashboardId);
  list.unshift({ ...entry, at: Date.now() });
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(list.slice(0, MAX_ENTRIES)));
  } catch {
    // 忽略存储失败
  }
}
