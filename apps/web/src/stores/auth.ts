import { create } from 'zustand';
import { ApiError } from '../api/error';
import { clearWorkspacesCache } from '../hooks/useWorkspaces';
import { tr } from '../i18n';
import type { LoginResponse, User } from '../api/types';

interface AuthState {
  token: string | null;
  user: User | null;
  /** 应用启动时是否已完成会话恢复检查 */
  ready: boolean;
  setSession: (token: string, user: User | null) => void;
  setUser: (user: User | null) => void;
  logout: () => void;
  markReady: () => void;
}

const STORAGE_KEY = 't2d.auth';

function loadStored(): { token: string | null; user: User | null } {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return { token: null, user: null };
    const parsed = JSON.parse(raw) as { token?: string; user?: User };
    return { token: typeof parsed.token === 'string' ? parsed.token : null, user: parsed.user ?? null };
  } catch {
    return { token: null, user: null };
  }
}

function persist(token: string | null, user: User | null): void {
  try {
    if (token) localStorage.setItem(STORAGE_KEY, JSON.stringify({ token, user }));
    else localStorage.removeItem(STORAGE_KEY);
  } catch {
    // localStorage 不可用时忽略（隐私模式等）
  }
}

const stored = loadStored();

export const useAuthStore = create<AuthState>((set) => ({
  token: stored.token,
  user: stored.user,
  ready: false,
  setSession: (token, user) => {
    persist(token, user);
    set({ token, user });
  },
  setUser: (user) => {
    persist(useAuthStore.getState().token, user);
    set({ user });
  },
  logout: () => {
    persist(null, null);
    clearWorkspacesCache();
    set({ token: null, user: null });
  },
  markReady: () => set({ ready: true }),
}));

export async function login(username: string, password: string): Promise<void> {
  const res = await fetch('/api/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  });
  if (!res.ok) {
    const msg = res.status === 401 ? tr('login.error.badCredentials') : tr('login.error.http', { status: res.status });
    throw new ApiError(res.status, msg);
  }
  const data = (await res.json()) as LoginResponse;
  clearWorkspacesCache();
  useAuthStore.getState().setSession(data.token, data.user);
}
