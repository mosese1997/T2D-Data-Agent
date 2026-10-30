import { useState } from 'react';
import type { Proposal } from './useAgentTask';
import DashboardCanvas from '../canvas/DashboardCanvas';
import { ErrorBox } from '../common/ui';
import { useI18n } from '../../i18n';

interface PatchProposalProps {
  proposal: Proposal;
  error: string | null;
  onApply: () => Promise<void>;
  onReject: () => Promise<void>;
}

export default function PatchProposal({ proposal, error, onApply, onReject }: PatchProposalProps) {
  const [busy, setBusy] = useState(false);
  const { t } = useI18n();

  const run = async (fn: () => Promise<void>) => {
    if (busy) return;
    setBusy(true);
    try {
      await fn();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="patch-card">
      <div className="patch-head">{t('patch.title')}</div>
      {proposal.diffSummary && <div className="patch-diff">{proposal.diffSummary}</div>}
      {proposal.previewCanvas && (
        <div className="patch-preview">
          <div className="patch-preview-label">{t('patch.preview')}</div>
          <DashboardCanvas canvas={proposal.previewCanvas} compact />
        </div>
      )}
      {error && <ErrorBox message={error} />}
      <div className="patch-actions">
        <button type="button" className="btn btn-primary" disabled={busy} onClick={() => void run(onApply)}>
          {busy ? t('common.processing') : t('patch.apply')}
        </button>
        <button type="button" className="btn btn-ghost" disabled={busy} onClick={() => void run(onReject)}>
          {t('common.reject')}
        </button>
      </div>
    </div>
  );
}
