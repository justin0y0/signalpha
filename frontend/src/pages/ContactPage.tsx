import { motion, useMotionValue, useSpring, useTransform } from 'framer-motion'
import { useEffect, useRef, useState } from 'react'
import {
  ArrowUpRight,
  AtSign,
  Briefcase,
  Check,
  Copy,
  Linkedin,
  MapPin,
  Sparkles,
  TerminalSquare,
} from 'lucide-react'

// ============================================================
//  Signalpha — Contact Page
//  3D parallax card + magnetic buttons + animated terminal.
// ============================================================

const EMAIL = 'justinyu0315@gmail.com'
const LINKEDIN_URL = 'https://www.linkedin.com/in/justin-yu-881727291'
const LINKEDIN_DISPLAY = 'in/justin-yu-881727291'

// ============================================================
//  Animated terminal block typing out the contact info
// ============================================================

const TERMINAL_LINES: { prompt?: string; text: string; tone?: 'cmd' | 'out' | 'warn' | 'ok' | 'comment' }[] = [
  { prompt: '$', text: 'whoami', tone: 'cmd' },
  { text: 'Justin Yu  \u00B7  Columbia MSAI', tone: 'out' },
  { prompt: '$', text: 'cat ./role.txt', tone: 'cmd' },
  { text: 'Looking for: quant research, ML / signals, applied AI', tone: 'out' },
  { prompt: '$', text: 'curl -s api.signalpha.app/about | jq .stack', tone: 'cmd' },
  { text: '"Python  \u00B7  PyTorch  \u00B7  XGBoost  \u00B7  TypeScript  \u00B7  SQL  \u00B7  Docker"', tone: 'out' },
  { prompt: '$', text: 'echo $REPLY_SLA', tone: 'cmd' },
  { text: '< 24h on weekdays', tone: 'ok' },
  { prompt: '$', text: '_', tone: 'cmd' },
]

function Terminal() {
  const [lineIdx, setLineIdx] = useState(0)
  const [charIdx, setCharIdx] = useState(0)

  useEffect(() => {
    if (lineIdx >= TERMINAL_LINES.length) return
    const line = TERMINAL_LINES[lineIdx]
    if (charIdx < line.text.length) {
      const speed = line.tone === 'cmd' ? 36 : 14
      const t = setTimeout(() => setCharIdx((c) => c + 1), speed)
      return () => clearTimeout(t)
    } else {
      const pause = line.tone === 'cmd' ? 220 : 90
      const t = setTimeout(() => {
        setLineIdx((i) => i + 1)
        setCharIdx(0)
      }, pause)
      return () => clearTimeout(t)
    }
  }, [charIdx, lineIdx])

  return (
    <div className="contact-terminal">
      <div className="contact-terminal__chrome">
        <span className="dot dot--r" />
        <span className="dot dot--y" />
        <span className="dot dot--g" />
        <div className="contact-terminal__title">
          <TerminalSquare size={12} /> signalpha — zsh
        </div>
      </div>
      <div className="contact-terminal__body">
        {TERMINAL_LINES.slice(0, lineIdx).map((line, i) => (
          <div key={i} className={`tline tline--${line.tone}`}>
            {line.prompt && <span className="tline__prompt">{line.prompt}</span>}
            <span>{line.text}</span>
          </div>
        ))}
        {lineIdx < TERMINAL_LINES.length && (
          <div className={`tline tline--${TERMINAL_LINES[lineIdx].tone}`}>
            {TERMINAL_LINES[lineIdx].prompt && (
              <span className="tline__prompt">{TERMINAL_LINES[lineIdx].prompt}</span>
            )}
            <span>{TERMINAL_LINES[lineIdx].text.slice(0, charIdx)}</span>
            <span className="tline__cursor" />
          </div>
        )}
      </div>
    </div>
  )
}

// ============================================================
//  Tilt card with mouse-tracked parallax (Apple-style)
// ============================================================

function TiltCard({ children }: { children: React.ReactNode }) {
  const ref = useRef<HTMLDivElement>(null)
  const x = useMotionValue(0)
  const y = useMotionValue(0)
  const rotateX = useSpring(useTransform(y, [-0.5, 0.5], [8, -8]), { stiffness: 150, damping: 18 })
  const rotateY = useSpring(useTransform(x, [-0.5, 0.5], [-8, 8]), { stiffness: 150, damping: 18 })
  const glowX = useTransform(x, [-0.5, 0.5], ['0%', '100%'])
  const glowY = useTransform(y, [-0.5, 0.5], ['0%', '100%'])

  const onMove = (e: React.MouseEvent) => {
    const r = ref.current?.getBoundingClientRect()
    if (!r) return
    x.set((e.clientX - r.left) / r.width - 0.5)
    y.set((e.clientY - r.top) / r.height - 0.5)
  }
  const onLeave = () => {
    x.set(0)
    y.set(0)
  }

  return (
    <motion.div
      ref={ref}
      onMouseMove={onMove}
      onMouseLeave={onLeave}
      className="tilt-card"
      style={{ rotateX, rotateY, transformStyle: 'preserve-3d' }}
    >
      <motion.div
        className="tilt-card__glow"
        style={{
          background: useTransform(
            [glowX, glowY],
            ([gx, gy]) =>
              `radial-gradient(420px circle at ${gx} ${gy}, rgba(56,189,248,0.18), transparent 55%)`,
          ) as any,
        }}
      />
      {children}
    </motion.div>
  )
}

// ============================================================
//  Copy-to-clipboard pill
// ============================================================

function CopyPill({ value, label }: { value: string; label: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <button
      className={`copy-pill ${copied ? 'copy-pill--ok' : ''}`}
      onClick={() => {
        navigator.clipboard.writeText(value).then(() => {
          setCopied(true)
          setTimeout(() => setCopied(false), 1600)
        })
      }}
      aria-label={`Copy ${label}`}
    >
      {copied ? <Check size={13} /> : <Copy size={13} />}
      <span>{copied ? 'Copied' : 'Copy'}</span>
    </button>
  )
}

// ============================================================
//  Main page
// ============================================================

export function ContactPage() {
  return (
    <div className="contact-page">
      {/* Background canvas of slowly drifting orbs */}
      <div className="contact-orbs" aria-hidden>
        <div className="orb orb--cyan" />
        <div className="orb orb--purple" />
        <div className="orb orb--emerald" />
      </div>

      {/* HERO */}
      <motion.section
        className="contact-hero"
        initial={{ opacity: 0, y: 18 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.55, ease: 'easeOut' }}
      >
        <div className="contact-hero__kicker">
          <Sparkles size={13} />
          <span>Get in touch</span>
        </div>
        <h1 className="contact-hero__title">
          Let's <span className="contact-hero__title-grad">build something</span> at the intersection of
          ML and markets.
        </h1>
        <p className="contact-hero__lede">
          Open to quant research roles, applied ML positions, and any conversation about post-earnings
          drift, ensemble models, or production-grade financial UI.
        </p>
      </motion.section>

      {/* MAIN GRID — left: contact card; right: terminal */}
      <div className="contact-grid">
        <motion.div
          initial={{ opacity: 0, y: 14 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.55, delay: 0.1 }}
        >
          <TiltCard>
            <div className="contact-card">
              <div className="contact-card__head">
                <div className="contact-card__avatar">JY</div>
                <div>
                  <div className="contact-card__name">Justin Yu</div>
                  <div className="contact-card__role">
                    <Briefcase size={12} />
                    Columbia MSAI · Quant ML
                  </div>
                  <div className="contact-card__loc">
                    <MapPin size={12} />
                    Los Angeles ↔ New York
                  </div>
                </div>
              </div>

              <div className="contact-divider" />

              <a className="contact-row" href={`mailto:${EMAIL}`}>
                <div className="contact-row__iconwrap contact-row__iconwrap--cyan">
                  <AtSign size={16} />
                </div>
                <div className="contact-row__body">
                  <div className="contact-row__label">Email</div>
                  <div className="contact-row__value">{EMAIL}</div>
                </div>
                <div className="contact-row__actions">
                  <CopyPill value={EMAIL} label="email" />
                  <span className="contact-row__open" aria-label="Open mail client">
                    <ArrowUpRight size={14} />
                  </span>
                </div>
              </a>

              <a className="contact-row" href={LINKEDIN_URL} target="_blank" rel="noreferrer noopener">
                <div className="contact-row__iconwrap contact-row__iconwrap--purple">
                  <Linkedin size={16} />
                </div>
                <div className="contact-row__body">
                  <div className="contact-row__label">LinkedIn</div>
                  <div className="contact-row__value">{LINKEDIN_DISPLAY}</div>
                </div>
                <div className="contact-row__actions">
                  <CopyPill value={LINKEDIN_URL} label="LinkedIn URL" />
                  <span className="contact-row__open" aria-label="Open LinkedIn">
                    <ArrowUpRight size={14} />
                  </span>
                </div>
              </a>

              <div className="contact-card__foot">
                <div className="contact-status">
                  <span className="contact-status__dot" />
                  <span>
                    Open to <strong>full-time</strong> &amp; <strong>internship</strong> opportunities
                  </span>
                </div>
              </div>
            </div>
          </TiltCard>
        </motion.div>

        <motion.div
          initial={{ opacity: 0, y: 14 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.55, delay: 0.18 }}
        >
          <Terminal />
        </motion.div>
      </div>

      {/* FOCUS CHIPS */}
      <motion.section
        className="contact-focus"
        initial={{ opacity: 0, y: 14 }}
        whileInView={{ opacity: 1, y: 0 }}
        viewport={{ once: true }}
        transition={{ duration: 0.55, delay: 0.05 }}
      >
        <div className="contact-focus__title">What I'd love to talk about</div>
        <div className="contact-focus__chips">
          {[
            'Quant research roles',
            'Earnings drift / PEAD',
            'Multi-modal financial NLP',
            'Walk-forward backtesting',
            'Bayesian / conformal uncertainty',
            'Production ML systems',
            'Any role at a multi-manager pod',
          ].map((c) => (
            <span key={c} className="contact-focus__chip">
              {c}
            </span>
          ))}
        </div>
      </motion.section>

      {/* PRIMARY CTA */}
      <motion.div
        className="contact-cta"
        initial={{ opacity: 0, y: 14 }}
        whileInView={{ opacity: 1, y: 0 }}
        viewport={{ once: true }}
        transition={{ duration: 0.55 }}
      >
        <a className="contact-cta__primary" href={`mailto:${EMAIL}?subject=Hello%20Justin`}>
          <AtSign size={15} />
          Send an email
          <ArrowUpRight size={15} />
        </a>
        <a
          className="contact-cta__secondary"
          href={LINKEDIN_URL}
          target="_blank"
          rel="noreferrer noopener"
        >
          <Linkedin size={15} />
          Connect on LinkedIn
        </a>
      </motion.div>
    </div>
  )
}
