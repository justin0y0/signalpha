import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { en } from './en'
import { zh } from './zh'

/**
 * Two-locale i18n, hand-rolled.
 *
 * react-i18next would add ~40 KB for interpolation and plural rules this site does not
 * need — two locales, no plural-sensitive copy, no runtime locale downloads. What it
 * does need is a guarantee that a missing translation degrades to readable English
 * rather than printing a raw key, so `t()` falls through zh -> en -> the key itself,
 * and the fallback is silent in production.
 *
 * English is the default and stays the source of truth: every key exists in `en` first,
 * and `zh` is typed against it so a typo in a Chinese key fails the build instead of
 * silently rendering English forever.
 */

export type Locale = 'en' | 'zh'

const DICTS = { en, zh } as const
const STORAGE_KEY = 'sa_locale'

type Ctx = {
  locale: Locale
  setLocale: (l: Locale) => void
  t: (key: keyof typeof en, vars?: Record<string, string | number>) => string
}

const I18nContext = createContext<Ctx | null>(null)

function readStored(): Locale {
  if (typeof localStorage === 'undefined') return 'en'
  const v = localStorage.getItem(STORAGE_KEY)
  return v === 'zh' ? 'zh' : 'en'
}

export function I18nProvider({ children }: { children: ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>('en')

  // Read the stored choice after mount rather than during render: reading
  // localStorage in the initial state would diverge from any pre-rendered HTML.
  useEffect(() => {
    setLocaleState(readStored())
  }, [])

  const setLocale = useCallback((l: Locale) => {
    setLocaleState(l)
    try {
      localStorage.setItem(STORAGE_KEY, l)
    } catch {
      /* private mode — the choice just won't persist */
    }
    document.documentElement.lang = l === 'zh' ? 'zh-CN' : 'en'
  }, [])

  useEffect(() => {
    document.documentElement.lang = locale === 'zh' ? 'zh-CN' : 'en'
  }, [locale])

  const t = useCallback(
    (key: keyof typeof en, vars?: Record<string, string | number>) => {
      const dict = DICTS[locale] as Partial<Record<keyof typeof en, string>>
      let out = dict[key] ?? en[key] ?? (key as string)
      if (vars) {
        for (const [k, v] of Object.entries(vars)) {
          out = out.replace(new RegExp(`\\{${k}\\}`, 'g'), String(v))
        }
      }
      return out
    },
    [locale],
  )

  const value = useMemo(() => ({ locale, setLocale, t }), [locale, setLocale, t])
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>
}

export function useT() {
  const ctx = useContext(I18nContext)
  if (!ctx) {
    // A component rendered outside the provider still has to render something
    // sensible rather than crash the page.
    return { locale: 'en' as Locale, setLocale: () => {}, t: ((k: keyof typeof en) => en[k] ?? k) as Ctx['t'] }
  }
  return ctx
}
