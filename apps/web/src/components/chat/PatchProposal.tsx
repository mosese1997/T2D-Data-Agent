import { useState } from 'react';
import type { Proposal } from './useAgentTask';
import DashboardCanvas from '../canvas/DashboardCanvas';
import { ErrorBox } from '../common/ui';

interface PatchProposalProps {
  proposal: Proposal;
  error: string | null;
  onApply: () => Promise<void>;
  onReject: () => Promise<void>;
}

export default function PatchProposal({ proposal, error, onApply, onReject }: PatchProposalProps) {
  const [busy, setBusy] = useState(false);

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
      <div className="patch-head">Agent 提议修改看板</div>
      {proposal.diffSummary && <div className="patch-diff">{proposal.diffSummary}</div>}
      {proposal.previewCanvas && (
        <div className="patch-preview">
          <div className="patch-preview-label">预览（应用后生效）</div>
          <DashboardCanvas canvas={proposal.previewCanvas} compact />
        </div>
      )}
      {error && <ErrorBox message={error} />}
      <div className="patch-actions">
        <button type="button" className="btn btn-primary" disabled={busy} onClick={() => void run(onApply)}>
          {busy ? '处理中…' : '应用修改'}
        </button>
        <button type="button" className="btn btn-ghost" disabled={busy} onClick={() => void run(onReject)}>
          拒绝
        </button>
      </div>
    </div>
  );
}
