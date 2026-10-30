import { create } from 'zustand';
import { tr } from '../i18n';
import type { HealthInfo } from '../api/types';

interface HealthState {
  health: HealthInfo | null;
  error: string | null;
  reload: () => Promise<void>;
}

async function fetchHealth(): Promise<HealthInfo> {
  const res = await fetch('/api/healthz');
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return (await res.json()) as HealthInfo;
}

export const useHealthStore = create<HealthState>((set) => ({
  health: null,
  error: null,
  reload: async () => {
    try {
      set({ health: await fetchHealth(), error: null });
    } catch (e) {
      set({ health: null, error: e instanceof Error ? e.message : tr('error.unknown') });
    }
  },
}));
