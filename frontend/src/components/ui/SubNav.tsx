import { motion } from 'framer-motion'
import type { ReactNode } from 'react'

/**
 * In-page section switcher.
 *
 * The top nav had eleven entries, five of which ("Backtest", "Performance",
 * "Simulator", "Track Record", "Showdown") were all views of the same ML signal.
 * Related views now live behind one nav entry and switch here, so the top nav says
 * what the product does rather than how many ways it can plot one number.
 */

export type SubNavItem = { key: string; label: string; icon?: ReactNode }

type Props = {
  items: SubNavItem[]
  active: string
  onChange: (key: string) => void
}

export function SubNav({ items, active, onChange }: Props) {
  return (
    <div className="subnav" role="tablist">
      {items.map((item) => {
        const isActive = item.key === active
        return (
          <button
            key={item.key}
            role="tab"
            aria-selected={isActive}
            className={`subnav__item${isActive ? ' is-active' : ''}`}
            onClick={() => onChange(item.key)}
          >
            {item.icon && <span className="subnav__icon">{item.icon}</span>}
            {item.label}
            {isActive && <motion.span layoutId="subnav-underline" className="subnav__underline" />}
          </button>
        )
      })}
    </div>
  )
}
