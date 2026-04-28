import { ArrowDown, ArrowUp, Minus } from 'lucide-react'
import { Badge } from './Badge'

type Props = {
  direction?: string | null
  confidence?: number | null
}

export function DirectionBadge({ direction, confidence }: Props) {
  if (!direction) return <Badge variant="default">—</Badge>
  const dir = direction.toUpperCase()
  const conf = confidence != null ? ` · ${Math.round(confidence * 100)}%` : ''
  if (dir === 'UP')
    return <Badge variant="up" icon={<ArrowUp size={12} strokeWidth={2.5} />}>UP{conf}</Badge>
  if (dir === 'DOWN')
    return <Badge variant="down" icon={<ArrowDown size={12} strokeWidth={2.5} />}>DOWN{conf}</Badge>
  return <Badge variant="flat" icon={<Minus size={12} strokeWidth={2.5} />}>FLAT{conf}</Badge>
}
