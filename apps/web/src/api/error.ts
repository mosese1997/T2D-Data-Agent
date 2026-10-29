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
