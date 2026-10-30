import { useT } from '../i18n'

/**
 * The condition-rule editor (services/library.py t_rule): trade one ticker, watch any, enter
 * when ALL entry conditions hold at a close, leave when ANY exit condition does. Also the
 * plain-language rendering of a rule, used wherever a rule is named.
 */
export type Ind = { f: string; n?: number; t?: string }
export type Cond = { a: Ind; op: '>' | '<' | '>=' | '<='; b: Ind | number; k?: number }
export type Rule = { trade: string; signal?: string; alt?: string; entry: Cond[]; exit?: Cond[]; max_hold?: number }

export const INDS = ['close', 'open', 'sma', 'ema', 'ret', 'rsi', 'high', 'low', 'drawdown', 'vol', 'ibs', 'gap', 'down_days', 'up_days'] as const
const NEEDS_N = new Set(['sma', 'ema', 'ret', 'rsi', 'high', 'low', 'drawdown', 'vol'])
const PCT = new Set(['ret', 'drawdown', 'gap'])

export const TQQQ_EXAMPLE: Rule = {
  trade: 'TQQQ', signal: 'QQQ',
  entry: [{ a: { f: 'close' }, op: '>', b: { f: 'sma', n: 200 }, k: 1.05 }, { a: { f: 'ret', n: 1 }, op: '<', b: -0.015 }],
  exit: [{ a: { f: 'close' }, op: '<', b: { f: 'sma', n: 200 }, k: 0.95 }],
}

export function useRuleText() {
  const { t } = useT()
  const ind = (x: Ind, sig: string) => `${x.t && x.t !== sig ? `${x.t} ` : ''}${t(`rb.f.${x.f}` as 'rb.f.close', { n: x.n ?? '' })}`
  const cond = (c: Cond, sig: string) => {
    const b = typeof c.b === 'number'
      ? (PCT.has(c.a.f) ? `${(c.b * 100).toFixed(2).replace(/\.?0+$/, '')}%` : String(c.b))
      : `${c.k && c.k !== 1 ? `${c.k}× ` : ''}${ind(c.b, sig)}`
    return `${ind(c.a, sig)} ${c.op} ${b}`
  }
  return (r: Rule) => {
    const sig = r.signal || r.trade
    const en = r.entry.map((c) => cond(c, sig)).join(t('rb.and'))
    const ex = (r.exit ?? []).map((c) => cond(c, sig)).join(t('rb.or'))
    return t('rb.text', { trade: r.trade, sig, en, ex: ex ? t('rb.exitWhen', { ex }) : t('rb.whileTrue') })
      + (r.alt ? t('rb.alt', { alt: r.alt }) : '') + (r.max_hold ? t('rb.max', { n: r.max_hold }) : '')
  }
}

function IndEdit({ v, onChange, sig }: { v: Ind; onChange: (x: Ind) => void; sig: string }) {
  const { t } = useT()
  return (
    <span className="rb-ind">
      <input className="rb-t" value={v.t ?? ''} placeholder={sig} onChange={(e) => onChange({ ...v, t: e.target.value.toUpperCase() || undefined })} />
      <select value={v.f} onChange={(e) => onChange({ f: e.target.value, t: v.t, n: NEEDS_N.has(e.target.value) ? (v.n ?? (e.target.value === 'ret' ? 1 : 20)) : undefined })}>
        {INDS.map((f) => <option key={f} value={f}>{t(`rb.f.${f}` as 'rb.f.close', { n: 'n' })}</option>)}
      </select>
      {NEEDS_N.has(v.f) && <input className="rb-n" type="number" min={1} max={504} value={v.n ?? ''} onChange={(e) => onChange({ ...v, n: Number(e.target.value) })} />}
    </span>
  )
}

function CondEdit({ c, onChange, onDel, sig }: { c: Cond; onChange: (x: Cond) => void; onDel: () => void; sig: string }) {
  const { t } = useT()
  const num = typeof c.b === 'number'
  const pct = PCT.has(c.a.f)
  return (
    <div className="rb-cond">
      <IndEdit v={c.a} sig={sig} onChange={(a) => onChange({ ...c, a })} />
      <select className="rb-op" value={c.op} onChange={(e) => onChange({ ...c, op: e.target.value as Cond['op'] })}>
        {['>', '<', '>=', '<='].map((o) => <option key={o}>{o}</option>)}
      </select>
      {num ? (
        <span className="rb-ind">
          <input className="rb-num" type="number" step="any" value={pct ? +((c.b as number) * 100).toFixed(4) : (c.b as number)}
            onChange={(e) => onChange({ ...c, b: pct ? Number(e.target.value) / 100 : Number(e.target.value) })} />{pct && '%'}
        </span>
      ) : (
        <span className="rb-ind">
          <input className="rb-k" type="number" step="0.01" min={0.2} max={5} value={c.k ?? 1} onChange={(e) => onChange({ ...c, k: Number(e.target.value) })} />×
          <IndEdit v={c.b as Ind} sig={sig} onChange={(b) => onChange({ ...c, b })} />
        </span>
      )}
      <button className="ap-link" onClick={() => onChange(num ? { ...c, b: { f: 'sma', n: 200 }, k: 1 } : { ...c, b: 0, k: undefined })}>{num ? t('rb.vsInd') : t('rb.vsNum')}</button>
      <button className="ap-link rb-del" onClick={onDel} aria-label={t('rb.del')}>×</button>
    </div>
  )
}

export function RuleBuilder({ rule, onChange }: { rule: Rule; onChange: (r: Rule) => void }) {
  const { t } = useT()
  const text = useRuleText()
  const sig = rule.signal || rule.trade
  const list = (k: 'entry' | 'exit') => (
    <div className="rb-list">
      <span className="rb-label">{t(k === 'entry' ? 'rb.entry' : 'rb.exit')}</span>
      {(rule[k] ?? []).map((c, i) => (
        <CondEdit key={i} c={c} sig={sig} onChange={(x) => onChange({ ...rule, [k]: (rule[k] ?? []).map((y, j) => (j === i ? x : y)) })}
          onDel={() => onChange({ ...rule, [k]: (rule[k] ?? []).filter((_, j) => j !== i) })} />
      ))}
      {(rule[k] ?? []).length < 5 && <button className="ap-link" onClick={() => onChange({ ...rule, [k]: [...(rule[k] ?? []), { a: { f: 'close' }, op: '>', b: { f: 'sma', n: 200 }, k: 1 }] })}>{t('rb.add')}</button>}
    </div>
  )
  return (
    <div className="rb">
      <div className="rb-top">
        <label>{t('rb.trade')}<input value={rule.trade} onChange={(e) => onChange({ ...rule, trade: e.target.value.toUpperCase() })} /></label>
        <label>{t('rb.signal')}<input value={rule.signal ?? ''} placeholder={rule.trade} onChange={(e) => onChange({ ...rule, signal: e.target.value.toUpperCase() || undefined })} /></label>
        <label>{t('rb.altL')}<input value={rule.alt ?? ''} placeholder={t('rb.cash')} onChange={(e) => onChange({ ...rule, alt: e.target.value.toUpperCase() || undefined })} /></label>
        <label>{t('rb.maxL')}<input type="number" min={1} max={504} value={rule.max_hold ?? ''} onChange={(e) => onChange({ ...rule, max_hold: Number(e.target.value) || undefined })} /></label>
      </div>
      {list('entry')}
      {list('exit')}
      <p className="rb-say">{text(rule)}</p>
    </div>
  )
}
