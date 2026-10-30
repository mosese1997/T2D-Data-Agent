import { useState } from 'react';
import { useI18n } from '../../i18n';

interface ClarificationFormProps {
  question: string;
  onSubmit: (content: string) => Promise<void>;
}

export default function ClarificationForm({ question, onSubmit }: ClarificationFormProps) {
  const [value, setValue] = useState('');
  const [busy, setBusy] = useState(false);
  const { t } = useI18n();

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
      <div className="clarify-title">{t('clarify.title')}</div>
      <div className="clarify-question">{question}</div>
      <textarea
        className="clarify-input"
        value={value}
        rows={2}
        placeholder={t('clarify.placeholder')}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            void submit();
          }
        }}
      />
      <button type="button" className="btn btn-primary btn-sm" disabled={busy || !value.trim()} onClick={() => void submit()}>
        {busy ? t('common.submitting') : t('clarify.submit')}
      </button>
    </div>
  );
}
