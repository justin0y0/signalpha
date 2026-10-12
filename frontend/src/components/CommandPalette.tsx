import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AnimatePresence, motion } from 'framer-motion'
import { useUpcoming } from '../hooks/useUpcoming'
import { DESKS, JOURNEY, META } from '../lib/journey'
import { useT } from '../i18n'

/**
 * ⌘K — jump to any ticker or page.
 *
 * The product is organised around tickers, and before this the only way to reach one
 * was to find its row in the calendar. Typing a symbol that is not on the calendar
 * still opens its page: the deep dive works for any tracked name.
 */
type Item = { key: string; label: string; hint: string; code?: string; to: string; group: 'tickers' | 'pages' }

export function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useT()
  const nav = useNavigate()
  const upcoming = useUpcoming()
  const [q, setQ] = useState('')
  const [at, setAt] = useState(0)
  const inputRef = useRef<HTMLInputElement | null>(null)

  useEffect(() => { if (open) { setQ(''); setAt(0); setTimeout(() => inputRef.current?.focus(), 30) } }, [open])

  const items = useMemo<Item[]>(() => {
    const query = q.trim().toUpperCase()
    const seen = new Set<string>()
    const tickers: Item[] = []
    for (const e of upcoming) {
      if (seen.has(e.ticker)) continue
      const hay = `${e.ticker} ${(e.company_name ?? '').toUpperCase()}`
      if (query && !hay.includes(query)) continue
      seen.add(e.ticker)
      tickers.push({
        key: `t-${e.ticker}`, code: e.ticker, label: e.company_name ?? e.ticker,
        hint: `${e.earnings_date.slice(5)}${e.prob_move != null ? ` · ${(e.prob_move * 100).toFixed(0)}%` : ''}`,
        to: `/predict/${e.ticker}?earnings_date=${e.earnings_date}`, group: 'tickers',
      })
      if (tickers.length >= (query ? 8 : 5)) break
    }
    if (query && /^[A-Z.]{1,6}$/.test(query) && !seen.has(query)) {
      tickers.push({ key: `t-raw-${query}`, code: query, label: t('cmdk.openTicker'), hint: '↵', to: `/predict/${query}`, group: 'tickers' })
    }
    const pages: Item[] = [...JOURNEY, ...DESKS, ...META]
      .map((p) => ({ key: `p-${p.to}`, label: t(p.nav as 'nav.calendar'), hint: p.to, to: p.to, group: 'pages' as const }))
      .filter((p) => !query || p.label.toUpperCase().includes(query))
    return [...tickers, ...pages]
  }, [q, upcoming, t])

  useEffect(() => { setAt(0) }, [q])

  const go = (it?: Item) => { if (!it) return; onClose(); nav(it.to) }
  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); setAt((a) => Math.min(items.length - 1, a + 1)) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setAt((a) => Math.max(0, a - 1)) }
    else if (e.key === 'Enter') { e.preventDefault(); go(items[at]) }
    else if (e.key === 'Escape') onClose()
  }

  let lastGroup = ''
  return (
    <AnimatePresence>
      {open && (
        <motion.div className="cmdk-veil" onClick={onClose} initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.12 }}>
          <motion.div className="cmdk" role="dialog" aria-modal="true" aria-label={t('cmdk.aria')} onClick={(e) => e.stopPropagation()}
            initial={{ y: -12, opacity: 0, scale: 0.98 }} animate={{ y: 0, opacity: 1, scale: 1 }} exit={{ y: -8, opacity: 0 }}
            transition={{ duration: 0.18, ease: [0.2, 0.7, 0.2, 1] }}>
            <input ref={inputRef} className="cmdk__input" value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={onKey}
              placeholder={t('cmdk.placeholder')} spellCheck={false} autoComplete="off" />
            <div className="cmdk__list">
              {items.length === 0 && <div className="cmdk__empty">{t('cmdk.empty')}</div>}
              {items.map((it, i) => {
                const head = it.group !== lastGroup ? <div className="cmdk__group">{t(`cmdk.${it.group}` as 'cmdk.tickers')}</div> : null
                lastGroup = it.group
                return (
                  <div key={it.key}>
                    {head}
                    <button type="button" className={`cmdk__item${i === at ? ' is-on' : ''}`} onMouseEnter={() => setAt(i)} onClick={() => go(it)}>
                      {it.code && <b>{it.code}</b>}
                      <span>{it.label}</span>
                      <i>{it.hint}</i>
                    </button>
                  </div>
                )
              })}
            </div>
            <div className="cmdk__foot"><span>↑↓ {t('cmdk.move')}</span><span>↵ {t('cmdk.open')}</span><span>esc {t('cmdk.close')}</span></div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
