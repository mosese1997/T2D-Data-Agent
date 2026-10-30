import { ApiError } from './error';
import { useAuthStore } from '../stores/auth';
import { tr } from '../i18n';

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const token = useAuthStore.getState().token;
  const headers: Record<string, string> = {};
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body !== undefined) headers['Content-Type'] = 'application/json';

  const res = await fetch(path, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

  if (res.status === 401) {
    // 统一 401 处理：清空本地会话，路由层会跳转到登录页
    if (token) useAuthStore.getState().logout();
    throw new ApiError(401, tr('error.sessionExpired'));
  }

  if (!res.ok) {
    let payload = '';
    try {
      payload = await res.text();
    } catch {
      payload = '';
    }
    throw new ApiError(res.status, tr('error.requestFailed', { status: res.status }), payload);
  }

  return (await res.json()) as T;
}

export const api = {
  get: <T>(path: string) => request<T>('GET', path),
  post: <T>(path: string, body?: unknown) => request<T>('POST', path, body ?? {}),
};
