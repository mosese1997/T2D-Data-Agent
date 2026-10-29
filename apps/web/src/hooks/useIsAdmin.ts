import { useWorkspaces } from './useWorkspaces';

/**
 * 当前用户是否是任意工作空间的管理员。
 * null = 工作空间列表尚未加载完成（调用方应显示加载态）。
 */
export function useIsAdmin(): boolean | null {
  const { workspaces } = useWorkspaces();
  if (workspaces === null) return null;
  return workspaces.some((w) => w.role === 'admin');
}
