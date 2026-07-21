import type { ReactNode } from 'react'
import { motion } from 'framer-motion'

/**
 * Shared KPI tile.
 *
 * Visual language is taken from the Simulator's `.sim-kpi`: a 2px glowing accent rail
 * on the left edge, an optional tinted icon chip, an uppercase letterspaced label, a
 * monospace value, and a quiet helper line. Calendar / Performance / Prediction
 * Deep-Dive previously rendered a flatter card with no rail and no icon, which is what
 * made those pages read as a different product from Simulator and Contact.
 */

type Accent = 'cyan' | 'purple' | 'emerald' | 'rose' | 'amber' | 'default'

type Props = {
  label: string
  value: ReactNode
  helper?: ReactNode
  accent?: Accent
  /** Optional lucide icon element, e.g. `<Target size={12} />`. */
  icon?: ReactNode
  delay?: number
}

const accentColor: Record<Accent, string> = {
  cyan: 'var(--accent-cyan)',
  purple: 'var(--accent-purple)',
  emerald: 'var(--accent-emerald)',
  rose: 'var(--accent-rose)',
  amber: 'var(--accent-amber)',
  default: 'var(--text-primary)',
}

export function StatCard({ label, value, helper, accent = 'default', icon, delay = 0 }: Props) {
  return (
    <motion.div
      className={`stat-card stat-card--${accent}`}
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, delay, ease: [0.25, 0.1, 0.25, 1] }}
    >
      <div className="stat-card__head">
        {icon && <span className="stat-card__icon">{icon}</span>}
        <div className="stat-label">{label}</div>
      </div>
      <div className="stat-value" style={{ color: accentColor[accent] }}>
        {value}
      </div>
      {helper !== undefined && helper !== null && (
        <div className="stat-helper">{helper}</div>
      )}
    </motion.div>
  )
}
