import { useAuthStore } from '../stores/auth';

export interface SseEvent {
  id: string | null;
  event: string;
  data: string;
}

export type SseState = 'connecting' | 'open' | 'reconnecting';

export interface SseHandlers {
  getToken: () => string | null;
  onEvent: (ev: SseEvent) => void;
  /** 返回 false 时不再重连 */
  shouldReconnect: () => boolean;
  onStateChange?: (state: SseState) => void;
  /** 每次断线准备重连前回调（可用于先拉一次任务事件补齐缺口） */
  onReconnect?: () => void | Promise<void>;
}

/**
 * 基于 fetch 的 SSE 客户端。
 * - 支持自定义请求头（Authorization），这是不用 EventSource 的原因；
 * - 断线后带 Last-Event-ID 请求头自动重连；
 * - 服务端主动结束流（任务终态）时按 shouldReconnect 决定是否重连。
 */
export class SseClient {
  private readonly url: string;
  private readonly handlers: SseHandlers;
  private abort: AbortController | null = null;
  private stopped = true;
  private lastId: string | null = null;
  private failures = 0;
  private static readonly SEP_RE = /\r?\n\r?\n/;

  constructor(url: string, handlers: SseHandlers) {
    this.url = url;
    this.handlers = handlers;
  }

  start(): void {
    if (!this.stopped) return;
    this.stopped = false;
    void this.run();
  }

  stop(): void {
    this.stopped = true;
    this.abort?.abort();
    this.abort = null;
  }

  private async run(): Promise<void> {
    while (!this.stopped) {
      this.handlers.onStateChange?.(this.failures === 0 ? 'connecting' : 'reconnecting');
      try {
        const headers: Record<string, string> = { Accept: 'text/event-stream' };
        const token = this.handlers.getToken();
        if (token) headers.Authorization = `Bearer ${token}`;
        if (this.lastId !== null) headers['Last-Event-ID'] = this.lastId;

        this.abort = new AbortController();
        const res = await fetch(this.url, {
          headers,
          signal: this.abort.signal,
          cache: 'no-store',
        });
        if (res.status === 401) {
          useAuthStore.getState().logout();
          this.stop();
          return;
        }
        if (!res.ok || !res.body) throw new Error(`SSE HTTP ${res.status}`);

        this.failures = 0;
        this.handlers.onStateChange?.('open');
        await this.pump(res.body);
        // 流正常结束（服务端关闭）——落到下方重连判断
      } catch {
        if (this.stopped) return;
      }

      if (this.stopped) return;
      if (!this.handlers.shouldReconnect()) {
        this.stop();
        return;
      }
      this.failures += 1;
      this.handlers.onStateChange?.('reconnecting');
      try {
        await this.handlers.onReconnect?.();
      } catch {
        // 补读失败不阻断重连
      }
      if (this.stopped) return;
      const delay = Math.min(500 * this.failures, 8000);
      await new Promise((resolve) => setTimeout(resolve, delay));
    }
  }

  private async pump(body: ReadableStream<Uint8Array>): Promise<void> {
    const reader = body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      for (;;) {
        const m = SseClient.SEP_RE.exec(buffer);
        if (!m) break;
        const chunk = buffer.slice(0, m.index);
        buffer = buffer.slice(m.index + m[0].length);
        const ev = parseSseChunk(chunk);
        if (ev) {
          if (ev.id !== null) this.lastId = ev.id;
          this.handlers.onEvent(ev);
        }
      }
    }
    // 流结束时可能残留最后一个没有空行结尾的事件
    if (buffer.length > 0) {
      const ev = parseSseChunk(buffer);
      if (ev) {
        if (ev.id !== null) this.lastId = ev.id;
        this.handlers.onEvent(ev);
      }
    }
  }
}

function parseSseChunk(chunk: string): SseEvent | null {
  let id: string | null = null;
  let event = 'message';
  const dataLines: string[] = [];
  for (const rawLine of chunk.split(/\r?\n/)) {
    if (rawLine === '' || rawLine.startsWith(':')) continue;
    const colon = rawLine.indexOf(':');
    const field = colon === -1 ? rawLine : rawLine.slice(0, colon);
    let value = colon === -1 ? '' : rawLine.slice(colon + 1);
    if (value.startsWith(' ')) value = value.slice(1);
    if (field === 'id') id = value;
    else if (field === 'event') event = value;
    else if (field === 'data') dataLines.push(value);
  }
  if (dataLines.length === 0 && id === null) return null;
  return { id, event, data: dataLines.join('\n') };
}
