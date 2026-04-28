import { motion } from 'framer-motion'
import { ArrowDown, ArrowUp, Loader2 } from 'lucide-react'
import { useQuote } from '../../hooks/useQuote'
import { Sparkline } from './Sparkline'

type Props = { ticker: string }

export function PriceTicker({ ticker }: Props) {
  const { data, loading, error } = useQuote(ticker, 60_000)

  if (error) {
    return <div className="price-live"><span className="tertiary">Quote unavailable</span></div>
  }
  if (!data) {
    return (
      <div className="price-live">
        <Loader2 size={18} className="tertiary" style={{ animation: 'spin 1s linear infinite' }} />
      </div>
    )
  }

  const positive = data.change >= 0
  const deltaColor = positive ? 'var(--up)' : 'var(--down)'
  const Icon = positive ? ArrowUp : ArrowDown

  return (
    <div className="price-live">
      <motion.div
        key={data.price}
        initial={{ opacity: 0.5, y: -2 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3 }}
        className="price-large mono"
      >
        ${data.price.toFixed(2)}
      </motion.div>
      <div className="price-delta mono" style={{ color: deltaColor, display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 4 }}>
        <Icon size={14} strokeWidth={2.5} />
        {positive ? '+' : ''}{data.change.toFixed(2)} ({positive ? '+' : ''}{data.change_pct.toFixed(2)}%)
      </div>
      {data.sparkline.length > 5 && (
        <div style={{ marginTop: 10, display: 'flex', justifyContent: 'flex-end' }}>
          <Sparkline data={data.sparkline} width={160} height={36} positive={positive} />
        </div>
      )}
      <div className="tertiary" style={{ fontSize: '0.7rem', marginTop: 8, display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 4 }}>
        {loading ? (
          <Loader2 size={10} style={{ animation: 'spin 1s linear infinite' }} />
        ) : (
          <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--up)', display: 'inline-block' }} />
        )}
        LIVE · 30d history
      </div>
    </div>
  )
}
