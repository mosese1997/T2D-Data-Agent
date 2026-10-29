import { useEffect, useState } from 'react';
import { api } from '../api/client';
import { errorMessage } from '../api/error';
import type { RowsResponse } from '../api/types';

// source 数据在画布内被多个组件共享，做模块级缓存（size=500 全量拉取）
const cache = new Map<string, RowsResponse>();
const inflight = new Map<string, Promise<RowsResponse>>();

export function fetchSourceRows(sourceId: string): Promise<RowsResponse> {
  const hit = cache.get(sourceId);
  if (hit) return Promise.resolve(hit);
  let p = inflight.get(sourceId);
  if (!p) {
    p = api
      .get<RowsResponse>(`/api/sources/${encodeURIComponent(sourceId)}/rows?page=1&size=500`)
      .then((r) => {
        cache.set(sourceId, r);
        inflight.delete(sourceId);
        return r;
      })
      .catch((e) => {
        inflight.delete(sourceId);
        throw e;
      });
    inflight.set(sourceId, p);
  }
  return p;
}

/** patch 应用后数据源可能变化，清空缓存强制重新拉取 */
export function invalidateSourceRows(): void {
  cache.clear();
}

export interface SourceRowsState {
  rows: RowsResponse | null;
  error: string | null;
  loading: boolean;
}

export function useSourceRows(sourceId: string | null | undefined): SourceRowsState {
  const [state, setState] = useState<SourceRowsState>({ rows: null, error: null, loading: false });

  useEffect(() => {
    if (!sourceId) {
      setState({ rows: null, error: null, loading: false });
      return;
    }
    const hit = cache.get(sourceId);
    if (hit) {
      setState({ rows: hit, error: null, loading: false });
      return;
    }
    let alive = true;
    setState({ rows: null, error: null, loading: true });
    fetchSourceRows(sourceId)
      .then((r) => {
        if (alive) setState({ rows: r, error: null, loading: false });
      })
      .catch((e) => {
        if (alive) setState({ rows: null, error: errorMessage(e), loading: false });
      });
    return () => {
      alive = false;
    };
  }, [sourceId]);

  return state;
}
