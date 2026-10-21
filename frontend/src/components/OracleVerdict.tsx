import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useT } from '../i18n'

/**
 * The Oracle desk's answer to its own headline question — "were they right?" — measured.
 *
 * Three ways to follow the people this desk watches, each backtested the way Autopilot's
 * strategies are (data_pipeline/research_misc.py, research_filings.py): trading the calls
 * the LLM reads out of their news, copying fund managers' 13F holdings, and buying when a
 * company's own officers and directors buy together. Only the last has an edge, and it is
 * the one Autopilot can trade; its live feed sits underneath.
 */
type V = { excess: number | null; t: number | null; n: number | null; cagr: number | null; spy: number | null } | null
type Data = {
  since: string | null
  companies: { ticker: string; insiders: number; value: number; last_filed: string; tier: string | null }[]
  signals: { ticker: string; session: string; exit_session: string }[]
  verdicts: { calls: { h1: { mean?: number; t?: number; n?: number }; h5: { mean?: number; t?: number; n?: number } }
    insider_cluster: V; clone_buffett: V; clone_ackman: V }
}

const pct = (v: number | null | undefined, d = 1) => (v == null ? '—' : `${v >= 0 ? '+' : '−'}${Math.abs(v * 100).toFixed(d)}%`)
const money = (v: number) => (v >= 1e6 ? `$${(v / 1e6).toFixed(1)}M` : `$${Math.round(v / 1000)}k`)

export function OracleVerdict() {
  const { t } = useT()
  const [d, setD] = useState<Data | null>(null)
  useEffect(() => {
    fetch('/api/v1/oracle/insiders').then((r) => (r.ok ? r.json() : null)).then(setD).catch(() => setD(null))
  }, [])
  if (!d) return null
  const v = d.verdicts
  const ic = v.insider_cluster
  const tiles = [
    { k: 'calls', ok: false, num: pct(v.calls.h5?.mean), t: v.calls.h5?.t, n: v.calls.h5?.n },
    { k: 'clone', ok: false, num: `${pct(v.clone_buffett?.excess)} / ${pct(v.clone_ackman?.excess)}`, t: v.clone_buffett?.t, n: v.clone_buffett?.n },
    { k: 'insider', ok: !!ic && (ic.t ?? 0) >= 2, num: pct(ic?.excess, 2), t: ic?.t, n: ic?.n },
  ]
  const clusters = d.companies.filter((c) => c.insiders >= 3)
  return (
    <section className="orc-verdict">
      <header>
        <h2>{t('oracle.v.h')}</h2>
        <p>{t('oracle.v.lede')}</p>
      </header>
      <div className="orc-verdict__tiles">
        {tiles.map((x) => (
          <div key={x.k} className={x.ok ? 'is-ok' : 'is-no'}>
            <span className="orc-verdict__k">{t(`oracle.v.${x.k}` as 'oracle.v.calls')}</span>
            <b>{x.num}</b>
            <span className="orc-verdict__s">{t(`oracle.v.${x.k}.s` as 'oracle.v.calls.s', { t: x.t != null ? x.t.toFixed(1) : '—', n: x.n ?? '—' })}</span>
            <em>{x.ok ? t('oracle.v.edge') : t('oracle.v.none')}</em>
          </div>
        ))}
      </div>
      <div className="orc-verdict__feed">
        <div className="orc-verdict__feedhead">
          <h3>{t('oracle.v.feed')}</h3>
          <Link to="/autopilot">{t('oracle.v.trade')} →</Link>
        </div>
        {d.companies.length === 0 ? (
          <p className="orc-verdict__empty">{t('oracle.v.empty')}</p>
        ) : (
          <ol>
            {(clusters.length ? clusters : d.companies).slice(0, 12).map((c) => (
              <li key={c.ticker} className={c.insiders >= 3 ? 'is-cluster' : ''}>
                <Link to={`/predict/${c.ticker}`}><b>{c.ticker}</b></Link>
                <span>{t('oracle.v.insiders', { n: c.insiders })}</span>
                <span>{money(c.value)}</span>
                <span className="orc-verdict__dim">{c.last_filed}</span>
              </li>
            ))}
          </ol>
        )}
        {d.since && <p className="orc-verdict__dim">{t('oracle.v.since', { d: d.since })}</p>}
      </div>
    </section>
  )
}
