import { useState, useEffect, useCallback, useRef } from 'react'
import { TickerDetailModal } from '../components/TickerDetailModal'
import { SectorTreemap } from '../components/SectorTreemap'
import { StockLogo } from '../components/StockLogo'
import { motion } from 'framer-motion'
import { Activity, Flame, Zap, TrendingUp, TrendingDown, Bell, BellOff, Star } from 'lucide-react'
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine } from 'recharts'

type Factor = { label: string; value: number }
type Ticker = {
  ticker: string; sector: string; sector_etf: string; price: number;
  atr20: number; sigma_bar: number; rsi2: number; regime_up: boolean; vol_z: number;
  s_score: number | null; kappa_ann: number | null; half_life_bars: number | null;
  beta_market: number | null; beta_sector: number | null;
  gao_r1: number | null; gao_eligible: boolean; gao_side: string | null;
  session: string; last_ts: string; spark: number[]; market_cap?: number;
  score: number; factors: Factor[]; primary: string | null;
}
type Signal = {
  ticker: string; sector: string; score: number; side: string; primary: string;
  factors: Factor[]; price: number; rsi2: number; s_score: number | null;
  half_life_bars: number | null; atr20: number; vol_z: number;
  intraday_ret: number; suggested_size: number; estimated_prob: number;
  exit_clock: string; timestamp: string; session: string;
  high_conviction: boolean; notified: boolean;
  news?: { title: string; publisher: string; url: string; minutes_ago: number | null }[];
  ai?: { why?: string; action?: string; rationale?: string; risk?: string; error?: string } | null;
}
type Trade = {
  ticker: string; side: string; score: number; primary: string;
  entry_time: string; exit_time: string;
  entry_price: number; exit_price: number;
  bars_held: number; minutes_held: number;
  size: number; pnl: number; return_pct: number;
  exit_reason: string; win: boolean;
}
type PulseData = {
  tickers: Ticker[]; signals: Signal[];
  sectors: { sector: string; avg_ret: number; count: number }[];
  market: { avg_return: number; breadth: number; avg_vol_z: number; avg_rsi: number; n_tickers: number };
  portfolio: { final_equity: number; total_return: number; trades: number; wins: number;
               win_rate: number; sharpe: number;
               equity_curve: { ts: string; equity: number }[]; trade_log: Trade[];
               by_engine: { [k: string]: { trades: number; wins: number; pnl: number; win_rate: number } };
               status?: string };
  notifications: { configured: boolean; has_token: boolean; has_chat_id: boolean; sent_last_hour: number };
  thresholds: { signal: number; notify: number };
  as_of: string;
}

function useCountUp(target: number, dur = 700): number {
  const [v, setV] = useState(target)
  const prev = useRef(target)
  useEffect(() => {
    const t0 = performance.now(), s = prev.current, d = target - s
    if (Math.abs(d) < 0.001) { setV(target); return }
    let raf = 0
    const step = (n: number) => {
      const p = Math.min(1, (n - t0) / dur)
      setV(s + d * (1 - Math.pow(1 - p, 3)))
      if (p < 1) raf = requestAnimationFrame(step)
      else prev.current = target
    }
    raf = requestAnimationFrame(step)
    return () => cancelAnimationFrame(raf)
  }, [target, dur])
  return v
}

function spark(vals: number[], w: number, h: number): string {
  if (vals.length < 2) return ''
  const mn = Math.min(...vals), mx = Math.max(...vals), r = mx - mn || 1
  return vals.map((v, i) => `${i === 0 ? 'M' : 'L'} ${((i / (vals.length - 1)) * w).toFixed(1)} ${(h - ((v - mn) / r) * h).toFixed(1)}`).join(' ')
}

export function PulsePage() {
  const [data, setData] = useState<PulseData | null>(null)
  const [loading, setLoading] = useState(true)
  const [now, setNow] = useState(new Date())
  const [selectedTicker, setSelectedTicker] = useState<string | null>(null)

  const load = useCallback(async () => {
    try { setData(await (await fetch('/api/v1/pulse')).json()) }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { load() }, [load])
  useEffect(() => { const t = setInterval(() => setNow(new Date()), 1000); return () => clearInterval(t) }, [])
  useEffect(() => { const t = setInterval(load, 60_000); return () => clearInterval(t) }, [load])

  if (loading || !data) return (
    <div className="mc-loading">
      <div className="mc-loading__scan" />
      <div className="mc-loading__text">SCANNING MARKET</div>
      <div className="mc-loading__sub">Computing multi-factor conviction scores…</div>
    </div>
  )

  const highConv = data.signals.filter(s => s.high_conviction)
  const medConv = data.signals.filter(s => !s.high_conviction)

  return (
    <div className="mc-page">
      <PulseHero data={data} now={now} highConv={highConv.length} />
      <NotifBanner status={data.notifications} sent={data.signals.filter(s => s.notified).length} />
      <MarketGauges data={data} />
      {highConv.length > 0 && (
        <motion.div className="mc-panel" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}>
          <div className="mc-panel__title">
            <Star size={14} /> HIGH CONVICTION SIGNALS
            <span className="mc-panel__sub">
              |score| ≥ {data.thresholds.notify} · sent to Telegram if configured
            </span>
          </div>
          <div className="pulse-hi">
            {highConv.map((s, i) => <HighConvCard key={i} sig={s} onClick={() => setSelectedTicker(s.ticker)} />)}
          </div>
        </motion.div>
      )}
      {medConv.length > 0 && (
        <motion.div className="mc-panel" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 }}>
          <div className="mc-panel__title">
            <Zap size={14} /> ACTIVE SIGNALS
            <span className="mc-panel__sub">|score| ≥ {data.thresholds.signal} · traded but not notified</span>
          </div>
          <div className="pulse-signals">
            {medConv.map((s, i) => <SignalCard key={i} sig={s} onClick={() => setSelectedTicker(s.ticker)} />)}
          </div>
        </motion.div>
      )}
      {data.signals.length === 0 && (
        <div className="mc-panel"><div className="mc-empty">Market is quiet. No signals above threshold.</div></div>
      )}
      <motion.div className="mc-panel" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.21 }}>
        <div className="mc-panel__title">
          🗺️ SECTOR TREEMAP
          <span className="mc-panel__sub">click any stock for full details · color = conviction</span>
        </div>
        <SectorTreemap
          tickers={data.tickers}
          onSelect={(t) => setSelectedTicker(t)}
        />
      </motion.div>
      <PortfolioPanel portfolio={data.portfolio} />
      <TickerDetailModal
        ticker={selectedTicker}
        onClose={() => setSelectedTicker(null)}
      />
    </div>
  )
}

function PulseHero({ data, now, highConv }: { data: PulseData; now: Date; highConv: number }) {
  return (
    <div className="mc-hero">
      <div className="mc-hero__scanlines" />
      <div className="mc-hero__grid" />
      <div className="mc-hero__content">
        <div className="mc-hero__top">
          <div className="mc-status"><span className="mc-status__dot" /><span className="mc-status__txt">SCANNING</span></div>
          <div className="mc-clock"><span className="mc-clock__time">{now.toLocaleTimeString('en-US', { hour12: false })}</span><span className="mc-clock__tz">ET</span></div>
          <div className="mc-system">
            PULSE · {data.market.n_tickers} TICKERS · {data.signals.length} SIGNALS · {highConv} HIGH-CONVICTION
          </div>
        </div>
        <div className="mc-hero__main">
          <div>
            <div className="mc-hero__eyebrow">MULTI-FACTOR CONVICTION SCANNER</div>
            <h1 className="mc-hero__title">Anomaly Detection · 6-Factor Score</h1>
            <p style={{ color: 'var(--text-secondary)', fontSize: '0.85rem', margin: '0.4rem 0 0', maxWidth: 720, lineHeight: 1.55 }}>
              Each ticker scored by 6 independent factors: RSI, MA distance, momentum, volume, gap, sector.
              Trades fire when |score| ≥ {data.thresholds.signal}. Phone alerts when |score| ≥ {data.thresholds.notify}.
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}

function NotifBanner({ status, sent }: { status: PulseData['notifications']; sent: number }) {
  if (status.configured) return (
    <div className="pulse-notif pulse-notif--on">
      <Bell size={14} />
      <span><b>Telegram alerts ON</b> · {sent} sent this scan · {status.sent_last_hour} in last hour</span>
    </div>
  )
  return (
    <div className="pulse-notif pulse-notif--off">
      <BellOff size={14} />
      <span>
        <b>Phone alerts not configured.</b> Set <code>TELEGRAM_BOT_TOKEN</code> and <code>TELEGRAM_CHAT_ID</code> in server <code>.env</code> to receive high-conviction signals.
      </span>
    </div>
  )
}

function MarketGauges({ data }: { data: PulseData }) {
  const m = data.market as any
  return (
    <div className="pulse-gauges">
      <Gauge label="SPY" value={`$${(m.spy_price || 0).toFixed(2)}`}
        accent="#38bdf8" sub="market factor anchor" />
      <Gauge label="AVG |s|" value={(m.avg_abs_s_score || 0).toFixed(2)}
        accent={(m.avg_abs_s_score || 0) > 1.0 ? '#fbbf24' : '#38bdf8'}
        sub="mean residual deviation" />
      <Gauge label="AVG RSI(2)" value={(m.avg_rsi2 || 0).toFixed(1)}
        accent={(m.avg_rsi2 || 50) > 70 ? '#f87171' : (m.avg_rsi2 || 50) < 30 ? '#4ade80' : '#38bdf8'}
        sub="Connors short-term" />
      <Gauge label="UPTREND" value={`${m.n_uptrend || 0}/${m.n_tickers || 0}`}
        accent={(m.n_uptrend || 0) > (m.n_tickers || 1) / 2 ? '#4ade80' : '#f87171'}
        sub="above 200-SMA" />
      <Gauge label="SIGNALS" value={data.signals.length.toString()}
        accent="#a78bfa" sub={`|score| ≥ ${data.thresholds.signal}`} />
    </div>
  )
}

function Gauge({ label, value, accent, sub }: { label: string; value: string; accent: string; sub: string }) {
  return (
    <div className="pulse-gauge" style={{ '--accent': accent } as React.CSSProperties}>
      <div className="pulse-gauge__label">{label}</div>
      <div className="pulse-gauge__value mono" style={{ color: accent }}>{value}</div>
      <div className="pulse-gauge__sub">{sub}</div>
      <div className="pulse-gauge__bar" />
    </div>
  )
}

function HighConvCard({ sig, onClick }: { sig: Signal; onClick?: () => void }) {
  const stars = Math.min(5, Math.max(1, Math.round(Math.abs(sig.score) * 6)))
  const color = sig.side === 'LONG' ? '#4ade80' : '#f87171'
  const engineLabel: { [k: string]: string } = {
    AL_REVERSION: 'Avellaneda-Lee',
    GAO_MOMENTUM: 'Gao 2018 intraday',
    CONNORS: 'Connors RSI(2)',
  }
  return (
    <motion.div className="pulse-hi-card pulse-clickable"
      initial={{ opacity: 0, scale: 0.95 }} animate={{ opacity: 1, scale: 1 }}
      onClick={onClick}
      style={{ borderColor: color, boxShadow: `0 0 32px -10px ${color}` }}>
      <div className="pulse-hi-card__top">
        <div className="pulse-hi-card__stars">{'★'.repeat(stars)}{'☆'.repeat(5 - stars)}</div>
        {sig.session !== 'market' && (
          <div className="pulse-hi-card__session">{sig.session.replace('_', '-').toUpperCase()}</div>
        )}
        {sig.notified && <div className="pulse-hi-card__notif"><Bell size={10} /> SENT</div>}
      </div>
      <div className="pulse-hi-card__id">
        <StockLogo ticker={sig.ticker} size={30} />
        <div>
          <div className="pulse-hi-card__ticker mono">{sig.ticker}</div>
          <div className="pulse-hi-card__price mono">${sig.price.toFixed(2)} · {sig.sector}</div>
        </div>
      </div>
      <div className="pulse-hi-card__engine" style={{ color }}>
        ENGINE: {engineLabel[sig.primary] || sig.primary}
        {sig.s_score !== null && <span style={{ marginLeft: '0.5rem', color: 'var(--text-tertiary)' }}>
          s = <b style={{ color }}>{sig.s_score >= 0 ? '+' : ''}{sig.s_score.toFixed(2)}</b>
          {sig.half_life_bars !== null && ` · HL ${sig.half_life_bars.toFixed(0)}b`}
        </span>}
      </div>
      <div className="pulse-hi-card__lcd">
        <div className="pulse-hi-card__score-l">CONVICTION</div>
        <div className="pulse-hi-card__score mono" style={{ color }}>
          {sig.score > 0 ? '+' : ''}{sig.score.toFixed(2)}
        </div>
      </div>
      <div className="pulse-hi-card__action">
        <span style={{ color, fontWeight: 800, fontSize: '1rem' }}>
          {sig.side === 'LONG' ? <TrendingUp size={14} /> : <TrendingDown size={14} />} {sig.side}
        </span>
        <span className="mono pulse-hi-card__size">${sig.suggested_size.toLocaleString()}</span>
      </div>
      <div className="pulse-hi-card__exit mono">
        target {sig.exit_clock} · est P(win) {(sig.estimated_prob * 100).toFixed(0)}%
        <span style={{ float: 'right', color: 'var(--text-tertiary)' }}>±1σ barriers</span>
      </div>
      <div className="pulse-hi-card__factors">
        <div className="pulse-hi-card__factors-l">FACTORS</div>
        {sig.factors.map((f, i) => (
          <div key={i} className="pulse-hi-card__factor">
            <span className="pulse-hi-card__factor-l">{f.label}</span>
            <span className="mono" style={{ color: f.value >= 0 ? '#4ade80' : '#f87171' }}>
              {f.value >= 0 ? '+' : ''}{f.value.toFixed(2)}
            </span>
          </div>
        ))}
      </div>

      {sig.ai && sig.ai.why && (
        <div className="pulse-hi-card__ai">
          <div className="pulse-hi-card__ai-l">🧠 AI ANALYSIS</div>
          <div className="pulse-hi-card__ai-why">{sig.ai.why}</div>
          <div className="pulse-hi-card__ai-grid">
            <div className="pulse-hi-card__ai-act">
              <span className="pulse-hi-card__ai-act-l">ACTION</span>
              <span className="pulse-hi-card__ai-act-v" style={{
                color: sig.ai.action === 'LONG' ? '#4ade80' :
                       sig.ai.action === 'SHORT' || sig.ai.action === 'FADE' ? '#f87171' : '#fbbf24'
              }}>{sig.ai.action}</span>
            </div>
            <div className="pulse-hi-card__ai-rat">{sig.ai.rationale}</div>
          </div>
          <div className="pulse-hi-card__ai-risk">
            <span style={{ color: '#fbbf24' }}>⚠ Risk:</span> {sig.ai.risk}
          </div>
        </div>
      )}

      {sig.news && sig.news.length > 0 && (
        <div className="pulse-hi-card__news">
          <div className="pulse-hi-card__news-l">📰 RECENT NEWS</div>
          {sig.news.slice(0, 3).map((n, i) => (
            <a key={i} href={n.url} target="_blank" rel="noopener noreferrer" className="pulse-hi-card__news-item">
              <div className="pulse-hi-card__news-title">{n.title}</div>
              <div className="pulse-hi-card__news-meta">
                {n.publisher} {n.minutes_ago !== null && `· ${n.minutes_ago}min ago`}
              </div>
            </a>
          ))}
        </div>
      )}
    </motion.div>
  )
}

function SignalCard({ sig, onClick }: { sig: Signal; onClick?: () => void }) {
  const color = sig.side === 'LONG' ? '#4ade80' : '#f87171'
  return (
    <motion.div className="pulse-signal pulse-clickable"
      initial={{ opacity: 0, scale: 0.97 }} animate={{ opacity: 1, scale: 1 }}
      onClick={onClick}
      style={{ borderColor: color }}>
      <div className="pulse-signal__top">
        <span className="pulse-signal__ticker mono">{sig.ticker}</span>
        <span className="pulse-signal__score mono" style={{ color }}>
          {sig.score > 0 ? '+' : ''}{sig.score.toFixed(2)}
        </span>
      </div>
      <div className="pulse-signal__price mono">${sig.price.toFixed(2)} · intraday {sig.intraday_ret >= 0 ? '+' : ''}{(sig.intraday_ret * 100).toFixed(2)}%</div>
      <div className="pulse-signal__action">
        <span style={{ color, fontWeight: 700 }}>
          {sig.side === 'LONG' ? '↑' : '↓'} {sig.side} · ${sig.suggested_size.toLocaleString()}
        </span>
      </div>
      <div className="pulse-signal__factors-mini">
        {sig.factors.slice(0, 3).map((f, i) => (
          <span key={i} className="pulse-signal__chip">
            {f.label}
            <b style={{ color: f.value >= 0 ? '#4ade80' : '#f87171' }}> {f.value >= 0 ? '+' : ''}{f.value.toFixed(2)}</b>
          </span>
        ))}
        {sig.factors.length > 3 && <span className="pulse-signal__chip pulse-signal__chip--more">+{sig.factors.length - 3}</span>}
      </div>
    </motion.div>
  )
}

: { tickers: Ticker[]; onSelect?: (t: string) => void }) {
  const color = (r: number) => {
    const i = Math.min(1, Math.abs(r) / 0.04)
    return r > 0 ? `rgba(74,222,128,${0.1 + i * 0.55})` : `rgba(248,113,113,${0.1 + i * 0.55})`
  }
  return (
    
  )
}

function PortfolioPanel({ portfolio: p }: { portfolio: PulseData['portfolio'] }) {
  const eq = useCountUp(p.final_equity, 900)
  const ret = useCountUp(p.total_return * 100, 900)
  return (
    <motion.div className="mc-panel" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.24 }}>
      <div className="mc-panel__title"><Activity size={14} /> SCANNER PORTFOLIO
        <span className="mc-panel__sub">$1M book · multi-factor signals · size scales with |score| · 1-hr hold · 5d</span></div>
      <div className="pulse-port">
        {p.status && (p.status === 'computing' || p.status === 'refreshing') && (
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: '0.7rem', color: '#fbbf24',
            padding: '0.4rem 0', borderBottom: '1px solid var(--border)', marginBottom: '0.5rem' }}>
            ⟳ Portfolio simulation running in background ({p.trades === 0 ? 'first load ~2min' : 'refreshing'})
          </div>
        )}
        <div className="pulse-port__lcd">
          <div className="pulse-port__lcd-label">EQUITY</div>
          <div className="pulse-port__lcd-val mono" style={{ color: p.total_return >= 0 ? '#4ade80' : '#f87171' }}>
            ${Math.round(eq).toLocaleString()}
          </div>
          <div className={`pulse-port__ret mono ${p.total_return >= 0 ? 'up' : 'down'}`}>
            {ret >= 0 ? '+' : ''}{ret.toFixed(2)}%
          </div>
        </div>
        <div className="pulse-port__stats">
          <div><span>TRADES</span><b className="mono">{p.trades}</b></div>
          <div><span>WIN RATE</span><b className="mono">{(p.win_rate * 100).toFixed(0)}%</b></div>
          <div><span>SHARPE</span><b className="mono">{p.sharpe.toFixed(2)}</b></div>
          <div><span>WINS</span><b className="mono">{p.wins}</b></div>
        </div>
        <div className="pulse-port__curve">
          {p.equity_curve.length > 1 && (
            <ResponsiveContainer width="100%" height={120}>
              <LineChart data={p.equity_curve} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
                <XAxis dataKey="ts" hide />
                <YAxis hide domain={['dataMin', 'dataMax']} />
                <ReferenceLine y={1_000_000} stroke="rgba(255,255,255,0.15)" strokeDasharray="3 3" />
                <Tooltip
                  content={({ active, payload }) => active && payload?.length ? (
                    <div className="mc-tt"><b className="mono">${Math.round(payload[0].value as number).toLocaleString()}</b></div>
                  ) : null}
                />
                <Line type="monotone" dataKey="equity" stroke={p.total_return >= 0 ? '#4ade80' : '#f87171'}
                  strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          )}
        </div>
      </div>
      {Object.keys(p.by_engine || {}).length > 0 && (
        <div className="pulse-by-engine">
          <div style={{ fontSize: '0.65rem', fontFamily: 'var(--font-mono)', letterSpacing: '0.1em', color: 'var(--text-tertiary)', margin: '0.8rem 0 0.4rem' }}>PERFORMANCE BY ENGINE</div>
          <div className="pulse-engine-grid">
            {Object.entries(p.by_engine).map(([eng, d]) => (
              <div key={eng} className="pulse-engine-card">
                <div className="pulse-engine-card__name">
                  {eng === 'AL_REVERSION' ? 'Avellaneda-Lee' :
                   eng === 'GAO_MOMENTUM' ? 'Gao 2018' :
                   eng === 'CONNORS' ? 'Connors RSI(2)' : eng}
                </div>
                <div className="pulse-engine-card__row">
                  <span>Trades</span><b className="mono">{d.trades}</b>
                </div>
                <div className="pulse-engine-card__row">
                  <span>Win rate</span>
                  <b className="mono" style={{ color: d.win_rate > 0.55 ? '#4ade80' : d.win_rate > 0.50 ? '#fbbf24' : '#f87171' }}>
                    {(d.win_rate * 100).toFixed(0)}%
                  </b>
                </div>
                <div className="pulse-engine-card__row">
                  <span>P&amp;L</span>
                  <b className="mono" style={{ color: d.pnl >= 0 ? '#4ade80' : '#f87171' }}>
                    {d.pnl >= 0 ? '+' : ''}${Math.round(d.pnl).toLocaleString()}
                  </b>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
      {p.trade_log.length > 0 && (
        <div className="pulse-trades">
          <div style={{ fontSize: '0.65rem', fontFamily: 'var(--font-mono)', letterSpacing: '0.1em', color: 'var(--text-tertiary)', margin: '0.5rem 0' }}>RECENT TRADES</div>
          <div className="mc-log">
            {p.trade_log.map((t, i) => (
              <div key={i} className="mc-log__row pulse-trade-row">
                <span className="mc-log__time mono pulse-trade-row__time">
                  IN  {t.entry_time.slice(5, 16).replace('T', ' ')}<br/>
                  OUT {t.exit_time.slice(5, 16).replace('T', ' ')}
                </span>
                <span className="mono pulse-trade-row__tkr" style={{ color: '#38bdf8' }}>
                  {t.ticker}<br/>
                  <span style={{ fontSize: '0.6rem', color: 'var(--text-tertiary)' }}>
                    {t.primary === 'AL_REVERSION' ? 'AL' : t.primary === 'GAO_MOMENTUM' ? 'GAO' : t.primary === 'CONNORS' ? 'CON' : '?'}
                  </span>
                </span>
                <span className="pulse-trade-row__side" style={{
                  color: t.side === 'LONG' ? '#4ade80' : '#f87171', fontWeight: 700, fontSize: '0.7rem'
                }}>{t.side}</span>
                <span className="mono pulse-trade-row__hold" style={{ fontSize: '0.62rem', color: 'var(--text-tertiary)' }}>
                  ${(t.size / 1000).toFixed(0)}k<br/>
                  {t.minutes_held}min
                </span>
                <span className="mono pulse-trade-row__exit" style={{
                  fontSize: '0.6rem', fontWeight: 700,
                  color: t.exit_reason === 'PROFIT' ? '#4ade80' :
                         t.exit_reason === 'STOP' ? '#f87171' : '#fbbf24'
                }}>{t.exit_reason}</span>
                <span className="mono pulse-trade-row__price" style={{ fontSize: '0.62rem', color: 'var(--text-tertiary)' }}>
                  ${t.entry_price.toFixed(2)} →<br/>${t.exit_price.toFixed(2)}
                </span>
                <span className="mono pulse-trade-row__pnl" style={{
                  color: t.win ? '#4ade80' : '#f87171', fontWeight: 700, textAlign: 'right'
                }}>
                  {t.pnl >= 0 ? '+' : ''}${Math.round(t.pnl).toLocaleString()}<br/>
                  <span style={{ fontWeight: 400, fontSize: '0.62rem' }}>
                    {(t.return_pct * 100).toFixed(2)}%
                  </span>
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </motion.div>
  )
}
