import { useT } from '../../i18n'

/**
 * Two-state language switch.
 *
 * A segmented control rather than a dropdown: with exactly two options a select costs
 * an extra click and hides the alternative. Each label is written in its own language —
 * 中文 is legible to someone who cannot read the English UI, which is the entire point
 * of a language control.
 */
export function LocaleToggle() {
  const { locale, setLocale, t } = useT()
  return (
    <div className="locale" role="group" aria-label={t('nav.language')}>
      <button
        type="button"
        className={`locale__opt${locale === 'en' ? ' is-active' : ''}`}
        aria-pressed={locale === 'en'}
        onClick={() => setLocale('en')}
        lang="en"
      >
        EN
      </button>
      <button
        type="button"
        className={`locale__opt${locale === 'zh' ? ' is-active' : ''}`}
        aria-pressed={locale === 'zh'}
        onClick={() => setLocale('zh')}
        lang="zh-CN"
      >
        中文
      </button>
    </div>
  )
}
