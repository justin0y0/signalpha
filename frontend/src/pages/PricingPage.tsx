import { useState } from 'react'
import { Link } from 'react-router-dom'
import { motion } from 'framer-motion'
import { Bot, Check, Clock, Copy, Sparkles } from 'lucide-react'
import { useHeadline, pct } from '../hooks/useHeadline'
import { useT } from '../i18n'

/**
 * Pro — the paid tier, offered honestly before it can be bought.
 *
 * There is no checkout yet. Instead of a fake "Buy" button this page states the price,
 * says plainly that Pro isn't on sale, and asks for an email plus which features the
 * visitor would pay for. That list (`pro_waitlist`) is the willingness-to-pay evidence
 * the launch decision should rest on.
 *
 * Every feature is labelled with its real state — live, live in beta, or coming — so the
 * page never sells something that does not exist.
 */

type Status = 'live' | 'beta' | 'soon'
type Feature = { key: string; want?: string; status: Status }

const FREE: Feature[] = [
  { key: 'pro.f.calendar', status: 'live' },
  { key: 'pro.f.arena', status: 'live' },
  { key: 'pro.f.evidence', status: 'live' },
  { key: 'pro.f.brief', status: 'live' },
]
const PRO: Feature[] = [
  { key: 'pro.f.straddle', want: 'straddle_check', status: 'beta' },
  { key: 'pro.f.alerts', want: 'alerts', status: 'soon' },
  { key: 'pro.f.arenaAlerts', want: 'arena_alerts', status: 'soon' },
  { key: 'pro.f.portfolio', want: 'portfolio_risk', status: 'soon' },
  { key: 'pro.f.mcp', want: 'api_mcp', status: 'beta' },
  { key: 'pro.f.universe', want: 'full_universe', status: 'soon' },
]

export function PricingPage() {
  const { t } = useT()
  const headline = useHeadline()
  const b = headline?.breakout
  const [annual, setAnnual] = useState(true)
  const [email, setEmail] = useState('')
  const [wants, setWants] = useState<string[]>(['straddle_check', 'alerts'])
  const [state, setState] = useState<'idle' | 'sending' | 'done' | 'error'>('idle')
  const [msg, setMsg] = useState('')
  const [copied, setCopied] = useState(false)
  const MCP_URL = 'https://signalpha.app/api/mcp'
  const copy = async () => {
    try { await navigator.clipboard.writeText(MCP_URL); setCopied(true); setTimeout(() => setCopied(false), 1500) } catch { /* clipboard blocked */ }
  }

  const toggle = (w: string) => setWants((cur) => (cur.includes(w) ? cur.filter((x) => x !== w) : [...cur, w]))

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setState('sending')
    try {
      const r = await fetch('/api/v1/waitlist', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, plan: annual ? 'pro_annual' : 'pro_monthly', wants, source: 'pricing' }),
      })
      if (!r.ok) {
        const j = await r.json().catch(() => null)
        throw new Error(j?.detail ?? `HTTP ${r.status}`)
      }
      setState('done')
    } catch (err) {
      setState('error')
      setMsg(err instanceof Error ? err.message : 'failed')
    }
  }

  const statusChip = (s: Status) => (
    <span className={`pro-status pro-status--${s}`}>{t(`pro.status.${s}` as 'pro.status.live')}</span>
  )

  return (
    <div className="pro">
      <motion.header className="pro-hero" initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.35 }}>
        <span className="pro-hero__kicker"><Sparkles size={12} /> SignAlpha Pro</span>
        <h1 className="pro-hero__title">{t('pro.title')}</h1>
        <p className="pro-hero__lede">{t('pro.lede')}</p>
        {b && (
          <p className="pro-hero__proof">
            {t('pro.proof', { top: pct(b.top_decile.move_rate, 1), base: pct(b.base_rate, 1), n: b.top_decile.n.toLocaleString() })}{' '}
            <Link to="/model">{t('pro.proof.link')}</Link>
          </p>
        )}
      </motion.header>

      <div className="pro-toggle" role="group" aria-label={t('pro.billing')}>
        <button type="button" className={!annual ? 'is-on' : ''} onClick={() => setAnnual(false)}>{t('pro.monthly')}</button>
        <button type="button" className={annual ? 'is-on' : ''} onClick={() => setAnnual(true)}>{t('pro.annual')} <i>{t('pro.annualSave')}</i></button>
      </div>

      <div className="pro-plans">
        <section className="pro-plan">
          <h2>{t('pro.free.name')}</h2>
          <div className="pro-price"><b>$0</b><span>{t('pro.forever')}</span></div>
          <p className="pro-plan__for">{t('pro.free.for')}</p>
          <ul>
            {FREE.map((f) => <li key={f.key}><Check size={13} /> <span>{t(f.key as 'pro.f.calendar')}</span></li>)}
          </ul>
        </section>

        <section className="pro-plan pro-plan--pro">
          <span className="pro-plan__flag">{t('pro.founding')}</span>
          <h2>Pro</h2>
          <div className="pro-price">
            <b>{annual ? '$190' : '$19'}</b><span>{annual ? t('pro.perYear') : t('pro.perMonth')}</span>
            <s>{annual ? '$290' : '$29'}</s>
          </div>
          <p className="pro-plan__for">{t('pro.pro.for')}</p>
          <ul>
            {PRO.map((f) => (
              <li key={f.key}>
                {f.status === 'soon' ? <Clock size={13} /> : <Check size={13} />}
                <span>{t(f.key as 'pro.f.straddle')}</span>
                {statusChip(f.status)}
              </li>
            ))}
          </ul>

          {state === 'done' ? (
            <div className="pro-done"><Check size={15} /> {t('pro.done')}</div>
          ) : (
            <form className="pro-form" onSubmit={submit}>
              <p className="pro-form__q">{t('pro.form.q')}</p>
              <div className="pro-wants">
                {PRO.filter((f) => f.want).map((f) => (
                  <label key={f.want} className={wants.includes(f.want!) ? 'is-on' : ''}>
                    <input type="checkbox" checked={wants.includes(f.want!)} onChange={() => toggle(f.want!)} />
                    {t(`${f.key}.short` as 'pro.f.straddle.short')}
                  </label>
                ))}
              </div>
              <div className="pro-form__row">
                <input type="email" required placeholder="you@example.com" value={email}
                  onChange={(e) => setEmail(e.target.value)} aria-label={t('pro.form.email')} />
                <button type="submit" className="btn btn-primary" disabled={state === 'sending'}>
                  {state === 'sending' ? '…' : t('pro.form.cta')}
                </button>
              </div>
              {state === 'error' && <p className="pro-form__err">{msg}</p>}
              <p className="pro-form__fine">{t('pro.form.fine')}</p>
            </form>
          )}
        </section>
      </div>

      <section className="pro-agent" id="agents">
        <div>
          <h3><Bot size={15} /> {t('pro.agent.title')}</h3>
          <p>{t('pro.agent.lede')}</p>
          <div className="pro-agent__url">
            <code>{MCP_URL}</code>
            <button type="button" className="btn" onClick={copy} aria-label={t('pro.agent.copy')}>
              {copied ? <Check size={13} /> : <Copy size={13} />}
            </button>
          </div>
          <p className="pro-agent__prompt">{t('pro.agent.prompt')}</p>
        </div>
        <div>
          <p>{t('pro.agent.tools')}</p>
          <ul>
            <li><code>portfolio_earnings_risk</code> — {t('pro.agent.t1')}</li>
            <li><code>earnings_risk</code> — {t('pro.agent.t2')}</li>
            <li><code>upcoming_earnings</code> — {t('pro.agent.t3')}</li>
            <li><code>arena_standings</code> — {t('pro.agent.t4')}</li>
            <li><code>model_track_record</code> — {t('pro.agent.t5')}</li>
          </ul>
        </div>
      </section>

      <section className="pro-faq">
        {(['trade', 'advice', 'trust', 'when'] as const).map((k) => (
          <div key={k}>
            <h3>{t(`pro.faq.${k}.q` as 'pro.faq.trade.q')}</h3>
            <p>{t(`pro.faq.${k}.a` as 'pro.faq.trade.a')}</p>
          </div>
        ))}
      </section>
      <p className="pro-contact">{t('pro.contact')} <Link to="/contact">{t('nav.contact')}</Link></p>
    </div>
  )
}
