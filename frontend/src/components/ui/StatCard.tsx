import type { ReactNode } from 'react'
import { motion } from 'framer-motion'

type Props = {
  label: string
  value: ReactNode
  helper?: ReactNode
  accent?: 'cyan' | 'purple' | 'emerald' | 'rose' | 'default'
  delay?: number
}

const accentStyles: Record<NonNullable<Props['accent']>, string> = {
  cyan: 'var(--accent-cyan)',
  purple: 'var(--accent-purple)',
  emerald: 'var(--accent-emerald)',
  rose: 'var(--accent-rose)',
  default: 'var(--text-primary)',
}

export function StatCard({ label, value, helper, accent = 'default', delay = 0 }: Props) {
  return (
    <motion.div
      className="stat-card"
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, delay, ease: [0.25, 0.1, 0.25, 1] }}
    >
      <div className="stat-label">{label}</div>
      <div className="stat-value" style={{ color: accentStyles[accent] }}>
        {value}
      </div>
      {helper !== undefined && helper !== null && (
        <div className="stat-helper">{helper}</div>
      )}
    </motion.div>
  )
}
