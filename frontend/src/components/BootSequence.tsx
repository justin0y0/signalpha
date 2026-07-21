import { useEffect, useRef, useState } from 'react'
import { useRenderTier } from '../hooks/useRenderTier'

/**
 * A cold-start self-test, played once per session.
 *
 * The site is an instrument, so it boots like one: it reports what it is about to
 * show you before it shows you. Every line is a real number pulled live — how many
 * events are loaded, what the model actually scores against its baseline, how well
 * calibrated it is. Nothing here is decorative text; if a number is bad the boot
 * screen says so, which is the opposite of a splash screen.
 *
 * Lasts about 1.6s, runs once per tab (sessionStorage), skippable by any key or
 * click, and is skipped entirely on the reduced-motion tier. A load sequence that
 * cannot be dismissed is a toll booth, not an entrance.
 */

type Line = { label: string; value: string; tone?: 'ok' | 'warn' | 'plain' }

export function BootSequence() {
  const tier = useRenderTier()
  const [done, setDone] = useState(true)
  const [step, setStep] = useState(0)
  const [lines, setLines] = useState<Line[]>([])
  const timers = useRef<number[]>([])

  useEffect(() => {
    if (tier === 'still') return
    if (sessionStorage.getItem('sa_booted') === '1') return
    setDone(false)

    let cancelled = false

    const load = async () => {
      const collected: Line[] = [{ label: 'link', value: 'signalpha.app · established', tone: 'ok' }]
      try {
        const [cal, perf] = await Promise.all([
          fetch('/api/v1/calendar?days_forward=90&days_back=0').then((r) => r.json()).catch(() => null),
          fetch('/api/v1/performance').then((r) => r.json()).catch(() => null),
        ])
        if (cal?.items) {
          const scored = cal.items.filter((e: { direction_prob_flat?: number | null }) => e.direction_prob_flat != null)
          const quiet = scored.filter((e: { direction_prob_flat: number }) => e.direction_prob_flat >= 0.6).length
          collected.push({ label: 'calendar', value: `${cal.items.length} events · ${scored.length} scored`, tone: 'ok' })
          collected.push({ label: 'reads quiet', value: `${quiet} of ${scored.length}`, tone: 'plain' })
        }
        if (perf?.confusion_matrix?.length === 3) {
          const cm = perf.confusion_matrix as number[][]
          const total = cm.flat().reduce((a, b) => a + b, 0)
          const acc = (cm[0][0] + cm[1][1] + cm[2][2]) / total
          const base = cm[1].reduce((a, b) => a + b, 0) / total
          const edge = (acc - base) * 100
          collected.push({ label: 'model', value: perf.model_version ?? 'unknown', tone: 'plain' })
          collected.push({
            label: 'vs baseline',
            value: `${acc >= base ? '+' : ''}${edge.toFixed(2)} pts`,
            tone: edge >= 0 ? 'ok' : 'warn',
          })
        }
      } catch {
        collected.push({ label: 'link', value: 'degraded — showing cached view', tone: 'warn' })
      }
      collected.push({ label: 'ready', value: 'not investment advice', tone: 'plain' })
      if (cancelled) return

      setLines(collected)
      collected.forEach((_, i) => {
        timers.current.push(window.setTimeout(() => setStep(i + 1), 170 * i + 120))
      })
      timers.current.push(window.setTimeout(finish, 170 * collected.length + 620))
    }

    const finish = () => {
      sessionStorage.setItem('sa_booted', '1')
      setDone(true)
    }

    const skip = () => finish()
    window.addEventListener('keydown', skip, { once: true })
    window.addEventListener('pointerdown', skip, { once: true })
    load()

    return () => {
      cancelled = true
      timers.current.forEach(clearTimeout)
      window.removeEventListener('keydown', skip)
      window.removeEventListener('pointerdown', skip)
    }
  }, [tier])

  if (done) return null

  return (
    <div className="boot" role="status" aria-live="polite">
      <div className="boot__inner">
        <div className="boot__mark">
          <span className="boot__scan" />
          SIGNALPHA
        </div>
        <div className="boot__lines">
          {lines.slice(0, step).map((l) => (
            <div key={l.label} className={`boot__line boot__line--${l.tone ?? 'plain'}`}>
              <span className="boot__label">{l.label}</span>
              <span className="boot__dots" />
              <span className="boot__value">{l.value}</span>
            </div>
          ))}
        </div>
        <div className="boot__hint">press any key to skip</div>
      </div>
    </div>
  )
}
