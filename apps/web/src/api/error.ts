export class ApiError extends Error {
  status: number;
  payload: string;

  constructor(status: number, message: string, payload = '') {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.payload = payload;
  }
}

export function errorMessage(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  if (e instanceof Error) return e.message;
  return '未知错误';
}

/** 优先取后端 JSON 响应里的 detail 字段（如 403/409 的具体原因），取不到再回退到通用消息 */
export function errorDetail(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.payload) {
      try {
        const parsed = JSON.parse(e.payload) as { detail?: unknown };
        if (typeof parsed.detail === 'string' && parsed.detail.trim() !== '') return parsed.detail;
      } catch {
        // payload 不是 JSON，走通用消息
      }
    }
    return e.message;
  }
  return errorMessage(e);
}
