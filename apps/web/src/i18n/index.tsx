import { createContext, useCallback, useContext, useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { zh } from './zh';
import { en } from './en';
import type { TranslateParams } from './types';

export type Locale = 'zh' | 'en';
export type { TranslateParams };

const STORAGE_KEY = 't2d.locale';

const DICTS: Record<Locale, Record<string, string>> = { zh, en };

/** 从 localStorage（t2d.locale）恢复；无记录时按 navigator.language 判断（zh 开头 → zh，否则 en） */
function detectLocale(): Locale {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved === 'zh' || saved === 'en') return saved;
  } catch {
    // localStorage 不可用时忽略（隐私模式等）
  }
  const nav = typeof navigator !== 'undefined' ? navigator.language : 'zh';
  return nav.toLowerCase().startsWith('zh') ? 'zh' : 'en';
}

/**
 * 模块级当前语言：Context 之外的代码（api/client、stores、useAgentTask 的事件回调等）
 * 通过 tr()/getLocale() 读取，抛错/事件到达那一刻的语言即所用语言。
 */
let currentLocale: Locale = detectLocale();

export function getLocale(): Locale {
  return currentLocale;
}

/**
 * 翻译函数（可在 React 外使用）。
 * - 字典值里的 {name} 占位符用 params 填充；
 * - key 缺失时用 fallback（未提供则回退到 key 本身，便于发现漏翻）。
 */
export function tr(key: string, params?: TranslateParams, fallback?: string): string {
  const dict = DICTS[currentLocale] ?? DICTS.zh;
  let text: string;
  if (Object.prototype.hasOwnProperty.call(dict, key)) {
    text = dict[key];
  } else if (fallback !== undefined) {
    text = fallback;
  } else {
    text = key;
  }
  if (params) {
    for (const [name, value] of Object.entries(params)) {
      text = text.split(`{${name}}`).join(String(value));
    }
  }
  return text;
}

interface I18nContextValue {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  /** 组件内翻译：t('key') / t('key', {n: 3}) */
  t: (key: string, params?: TranslateParams, fallback?: string) => string;
}

const I18nContext = createContext<I18nContextValue | null>(null);

export function I18nProvider({ children }: { children: ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>(currentLocale);

  const setLocale = useCallback((next: Locale) => {
    currentLocale = next;
    setLocaleState(next);
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // 忽略写入失败
    }
  }, []);

  // 同步 <html lang>，便于辅助技术与字体渲染
  useEffect(() => {
    document.documentElement.lang = locale === 'zh' ? 'zh-CN' : 'en';
  }, [locale]);

  const t = useCallback((key: string, params?: TranslateParams, fallback?: string) => tr(key, params, fallback), []);

  return <I18nContext.Provider value={{ locale, setLocale, t }}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18nContextValue {
  const ctx = useContext(I18nContext);
  if (!ctx) throw new Error('useI18n must be used within <I18nProvider>');
  return ctx;
}
