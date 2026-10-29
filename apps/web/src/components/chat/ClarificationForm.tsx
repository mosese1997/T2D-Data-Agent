import { useState } from 'react';

interface ClarificationFormProps {
  question: string;
  onSubmit: (content: string) => Promise<void>;
}

export default function ClarificationForm({ question, onSubmit }: ClarificationFormProps) {
  const [value, setValue] = useState('');
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    const text = value.trim();
    if (!text || busy) return;
    setBusy(true);
    try {
      await onSubmit(text);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="clarify-card">
      <div className="clarify-title">Agent 需要补充信息</div>
      <div className="clarify-question">{question}</div>
      <textarea
        className="clarify-input"
        value={value}
        rows={2}
        placeholder="输入你的回答…"
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            void submit();
          }
        }}
      />
      <button type="button" className="btn btn-primary btn-sm" disabled={busy || !value.trim()} onClick={() => void submit()}>
        {busy ? '提交中…' : '提交回答'}
      </button>
    </div>
  );
}
