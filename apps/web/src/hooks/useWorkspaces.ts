import { useEffect, useState } from 'react';
import { api } from '../api/client';
import { errorMessage } from '../api/error';
import type { Workspace } from '../api/types';

// 工作空间列表基本不变，做模块级缓存避免每个组件重复请求
let cache: Workspace[] | null = null;
let inflight: Promise<Workspace[]> | null = null;

export function useWorkspaces(): { workspaces: Workspace[] | null; error: string | null } {
  const [workspaces, setWorkspaces] = useState<Workspace[] | null>(cache);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (cache) {
      setWorkspaces(cache);
      return;
    }
    let alive = true;
    if (!inflight) {
      inflight = api
        .get<Workspace[]>('/api/workspaces')
        .then((ws) => {
          cache = ws;
          return ws;
        })
        .finally(() => {
          inflight = null;
        });
    }
    inflight
      .then((ws) => {
        if (alive) setWorkspaces(ws);
      })
      .catch((e) => {
        if (alive) setError(errorMessage(e));
      });
    return () => {
      alive = false;
    };
  }, []);

  return { workspaces, error };
}
