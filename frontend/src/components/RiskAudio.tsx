import { useEffect, useRef, useState } from 'react'
import { Volume2, VolumeX } from 'lucide-react'

/**
 * Concept G — the week has a sound.
 *
 * A chord built from the actual forecast distribution. Each upcoming event contributes
 * a voice; its pitch comes from the stock's expected move and its detune from how
 * uncertain the model is about it. A week the model reads as quiet lands on a
 * consonant stack and simply hums. A week full of expected breakouts detunes into a
 * beating, unstable cluster you can hear going wrong before you have read a number.
 *
 * Deliberately: off by default, one visible control, and started only from a real
 * click. Audio that begins on its own is both blocked by browsers and hostile. The
 * AudioContext is created on first enable and torn down on disable, so a muted visitor
 * pays nothing for this existing.
 */

type Props = {
  /** Quiet scores, one per upcoming event — P(FLAT), 0..1. */
  quietScores: number[]
}

const ROOT = 138.59 // C#3 — low enough to sit under a page without fighting speech.
const INTERVALS = [1, 1.5, 2, 3, 4, 4.5] // just fifths and octaves: consonant by construction

export function RiskAudio({ quietScores }: Props) {
  const [on, setOn] = useState(false)
  const ctxRef = useRef<AudioContext | null>(null)
  const nodesRef = useRef<{ osc: OscillatorNode; gain: GainNode }[]>([])

  const stop = () => {
    nodesRef.current.forEach(({ osc, gain }) => {
      try {
        gain.gain.setTargetAtTime(0, ctxRef.current!.currentTime, 0.08)
        osc.stop(ctxRef.current!.currentTime + 0.4)
      } catch {
        /* already stopped */
      }
    })
    nodesRef.current = []
    const ctx = ctxRef.current
    ctxRef.current = null
    if (ctx) window.setTimeout(() => ctx.close().catch(() => {}), 600)
  }

  useEffect(() => () => stop(), [])

  useEffect(() => {
    if (!on || !ctxRef.current || !nodesRef.current.length) return
    // Re-voice when the data changes without restarting the context.
    const ctx = ctxRef.current
    const mean = quietScores.length
      ? quietScores.reduce((a, b) => a + b, 0) / quietScores.length
      : 0.5
    nodesRef.current.forEach(({ osc }, i) => {
      // Calm weeks sit on clean intervals; agitation pulls each voice off pitch, and
      // the resulting beating is the sound of disagreement.
      const detune = (1 - mean) * 42 * (i % 2 === 0 ? 1 : -1)
      osc.detune.setTargetAtTime(detune, ctx.currentTime, 0.5)
    })
  }, [quietScores, on])

  const start = () => {
    const Ctor = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext
    if (!Ctor) return
    const ctx = new Ctor()
    ctxRef.current = ctx

    const master = ctx.createGain()
    master.gain.value = 0
    master.connect(ctx.destination)
    master.gain.setTargetAtTime(0.055, ctx.currentTime, 0.7)

    const mean = quietScores.length
      ? quietScores.reduce((a, b) => a + b, 0) / quietScores.length
      : 0.5

    INTERVALS.forEach((ratio, i) => {
      const osc = ctx.createOscillator()
      const gain = ctx.createGain()
      osc.type = i < 2 ? 'sine' : 'triangle'
      osc.frequency.value = ROOT * ratio
      osc.detune.value = (1 - mean) * 42 * (i % 2 === 0 ? 1 : -1)
      gain.gain.value = 0.5 / (i + 1.4)
      osc.connect(gain)
      gain.connect(master)
      osc.start()
      nodesRef.current.push({ osc, gain })
    })
  }

  const toggle = () => {
    if (on) {
      stop()
      setOn(false)
    } else {
      start()
      setOn(true)
    }
  }

  const mean = quietScores.length ? quietScores.reduce((a, b) => a + b, 0) / quietScores.length : 0.5

  return (
    <button
      className={`riskaudio${on ? ' is-on' : ''}`}
      onClick={toggle}
      aria-pressed={on}
      aria-label={on ? 'Mute the week' : 'Hear the week'}
      title={on ? 'Mute' : `Hear this week — ${mean >= 0.6 ? 'consonant, reads quiet' : 'detuned, reads unsettled'}`}
    >
      {on ? <Volume2 size={14} /> : <VolumeX size={14} />}
      <span className="riskaudio__label">{on ? 'muting' : 'hear the week'}</span>
      {on && (
        <span className="riskaudio__bars" aria-hidden="true">
          <i style={{ animationDelay: '0ms' }} />
          <i style={{ animationDelay: '160ms' }} />
          <i style={{ animationDelay: '320ms' }} />
        </span>
      )}
    </button>
  )
}
