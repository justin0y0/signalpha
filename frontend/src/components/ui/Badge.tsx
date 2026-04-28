import type { ReactNode } from 'react'
import clsx from 'clsx'

type Variant = 'up' | 'down' | 'flat' | 'accent' | 'default' | 'live'

type Props = {
  children: ReactNode
  variant?: Variant
  icon?: ReactNode
}

const variantMap: Record<Variant, string> = {
  up: 'badge-up',
  down: 'badge-down',
  flat: 'badge-flat',
  accent: 'badge-accent',
  default: '',
  live: 'badge-up badge-live',
}

export function Badge({ children, variant = 'default', icon }: Props) {
  return (
    <span className={clsx('badge', variantMap[variant])}>
      {icon}
      {children}
    </span>
  )
}
