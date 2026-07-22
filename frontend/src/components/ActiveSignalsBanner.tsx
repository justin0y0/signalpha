import { motion } from 'framer-motion'
import { Zap, TrendingUp, TrendingDown } from 'lucide-react'
import { StockLogo } from './StockLogo'
import { useT } from '../i18n'

interface Signal {
  ticker: string
  side: 'LONG' | 'SHORT'
  score: number
  primary?: string
}

interface Props {
  signals: any[]
  onSelect: (t: string) => void
}

const STRAT_TAG: Record<string, string> = {
  AL_REVERSION: 'AL',
  GAO_MOMENTUM: 'GAO',
  CONNORS: 'CN',
}

export function ActiveSignalsBanner({ signals, onSelect }: Props) {
  const { t } = useT()
  const longs = signals.filter((s: any) => s.side === 'LONG').length
  const shorts = signals.filter((s: any) => s.side === 'SHORT').length
  return (
    <motion.div className="asb"
      initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}>
      <div className="asb__head">
        <span className="asb__title">
          <Zap size={13} /> ACTIVE SIGNALS
        </span>
        <span className="asb__count">{signals.length}</span>
        <span className="asb__counts">
          <span className="asb__long">{longs}L</span>
          <span className="asb__short">{shorts}S</span>
        </span>
        <span className="asb__hint">{t('signals.clickAny')}</span>
      </div>
      {signals.length === 0 ? (
        <div className="asb__empty">
          No active signals · market in noise zone · waiting for cleaner setups
        </div>
      ) : (
        <div className="asb__strip">
          {signals.slice(0, 10).map((s: any, i: number) => (
            <motion.div key={s.ticker}
              className={`asb-card asb-card--${s.side.toLowerCase()}`}
              onClick={() => onSelect(s.ticker)}
              initial={{ opacity: 0, scale: 0.92 }}
              animate={{ opacity: 1, scale: 1 }}
              transition={{ delay: i * 0.03 }}
              whileHover={{ scale: 1.05, y: -2 }}
              whileTap={{ scale: 0.97 }}>
              <StockLogo ticker={s.ticker} size={28} />
              <div className="asb-card__body">
                <div className="asb-card__t">{s.ticker}</div>
                <div className="asb-card__strat">
                  {STRAT_TAG[s.primary || ''] || '—'}
                </div>
              </div>
              <div className="asb-card__score">
                {s.side === 'LONG' ? <TrendingUp size={11} /> : <TrendingDown size={11} />}
                <span>{s.score >= 0 ? '+' : ''}{s.score.toFixed(2)}</span>
              </div>
            </motion.div>
          ))}
          {signals.length > 10 && (
            <div className="asb-card asb-card--more">+{signals.length - 10}</div>
          )}
        </div>
      )}
    </motion.div>
  )
}
