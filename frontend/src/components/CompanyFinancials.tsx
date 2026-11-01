import { useEffect, useMemo, useState } from 'react'
import { useT } from '../i18n'

/**
 * What the company reported and the documents it reported in, from the SEC: quarterly
 * numbers out of the XBRL company facts (Q4 and quarterly cash flow derived where the
 * company only files annual or year-to-date values — marked), the EPS consensus beside
 * the reported figure, and every earnings release, 10-Q and 10-K linked to the SEC's
 * own copy (exhibits listed, PDFs flagged). Foreign filers only tag annual numbers.
 */
type Q = {
  end: string; revenue: number | null; revenue_yoy: number | null; gross_profit: number | null; gross_margin: number | null
  op_income: number | null; net_income: number | null; eps_diluted: number | null; ocf: number | null; capex: number | null
  fcf: number | null; derived: string[]
}
type A = { end: string; revenue: number | null; op_income: number | null; net_income: number | null; eps_diluted: number | null }
type Ex = { type: string; desc: string; url: string; pdf: boolean }
type Filing = {
  form: string; kind: 'earnings' | 'quarterly' | 'annual'; filed: string; accepted: string; period: string | null
  desc: string; url: string; index: string; exhibits?: Ex[]
}
type Est = { report_date: string; eps_estimate: number | null; eps_actual: number | null; surprise_pct: number | null }
type Data = { ticker: string; cik: string; name: string | null; currency: string | null; quarters: Q[]; annual: A[]; estimates: Est[]; filings: Filing[]; browse: string }

const money = (v: number | null | undefined, cur: string | null) => {
  if (v == null) return '—'
  const a = Math.abs(v), s = v < 0 ? '−' : ''
  const sym = cur === 'USD' || !cur ? '$' : ''
  const tail = cur && cur !== 'USD' ? ` ${cur}` : ''
  if (a >= 1e12) return `${s}${sym}${(a / 1e12).toFixed(2)}T${tail}`
  if (a >= 1e9) return `${s}${sym}${(a / 1e9).toFixed(2)}B${tail}`
  if (a >= 1e6) return `${s}${sym}${(a / 1e6).toFixed(1)}M${tail}`
  return `${s}${sym}${(a / 1e3).toFixed(0)}K${tail}`
}
const pct = (v: number | null | undefined) => (v == null ? '—' : `${v >= 0 ? '+' : '−'}${Math.abs(v * 100).toFixed(1)}%`)
const qLabel = (end: string) => {
  const d = new Date(`${end}T12:00:00`)
  return d.toLocaleDateString('en-US', { month: 'short', year: 'numeric' })
}
const exLabel = (e: Ex, t: (k: never) => string) =>
  e.type.startsWith('EX-99.1') ? t('cf.ex.release' as never) : e.type.startsWith('EX-99') ? t('cf.ex.supplement' as never).replace('{n}', e.type.replace('EX-', '')) : e.type

export function CompanyFinancials({ ticker }: { ticker: string }) {
  const { t } = useT()
  const [d, setD] = useState<Data | null>(null)
  const [failed, setFailed] = useState(false)
  const [docs, setDocs] = useState<'earnings' | 'all'>('earnings')
  useEffect(() => {
    setD(null); setFailed(false)
    fetch(`/api/v1/company/${encodeURIComponent(ticker)}/financials`)
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status))).then(setD).catch(() => setFailed(true))
  }, [ticker])

  // the consensus for the report that disclosed each quarter: filed 0-100 days after its end
  const estFor = useMemo(() => {
    const m: Record<string, Est> = {}
    for (const q of d?.quarters ?? []) {
      const end = new Date(q.end).getTime()
      const hit = (d?.estimates ?? []).filter((e) => {
        const gap = (new Date(e.report_date).getTime() - end) / 864e5
        return gap >= 0 && gap <= 100
      }).sort((a, b) => a.report_date.localeCompare(b.report_date))[0]
      if (hit) m[q.end] = hit
    }
    return m
  }, [d])

  if (failed || !d) return null
  const qs = d.quarters.slice(0, 8)
  const filings = d.filings.filter((f) => docs === 'all' || f.kind === 'earnings').slice(0, docs === 'all' ? 24 : 8)
  const derivedAny = qs.some((q) => q.derived.length)

  return (
    <section className="card cfin">
      <div className="cfin__head">
        <h3 className="card-title">{t('cf.title')}</h3>
        <span className="cfin__src">{t('cf.source')}{d.currency && d.currency !== 'USD' ? ` · ${d.currency}` : ''}</span>
      </div>

      {qs.length > 0 ? (
        <div className="table-scroll">
          <table className="data-table cfin__table">
            <thead>
              <tr>
                <th>{t('cf.quarter')}</th><th className="r">{t('cf.revenue')}</th><th className="r">{t('cf.yoy')}</th>
                <th className="r">{t('cf.gm')}</th><th className="r">{t('cf.op')}</th><th className="r">{t('cf.ni')}</th>
                <th className="r">{t('cf.eps')}</th><th className="r">{t('cf.est')}</th><th className="r">{t('cf.fcf')}</th>
              </tr>
            </thead>
            <tbody>
              {qs.map((q) => {
                const e = estFor[q.end]
                const mark = (f: string) => (q.derived.includes(f) ? <sup title={t('cf.derived')}>*</sup> : null)
                return (
                  <tr key={q.end} style={{ cursor: 'default' }}>
                    <td className="mono">{qLabel(q.end)}</td>
                    <td className="mono r">{money(q.revenue, d.currency)}{mark('revenue')}</td>
                    <td className={`mono r ${q.revenue_yoy == null ? '' : q.revenue_yoy >= 0 ? 'is-up' : 'is-down'}`}>{pct(q.revenue_yoy)}</td>
                    <td className="mono r">{q.gross_margin == null ? '—' : `${(q.gross_margin * 100).toFixed(1)}%`}</td>
                    <td className="mono r">{money(q.op_income, d.currency)}{mark('op_income')}</td>
                    <td className="mono r">{money(q.net_income, d.currency)}{mark('net_income')}</td>
                    <td className="mono r">{q.eps_diluted == null ? '—' : q.eps_diluted.toFixed(2)}{mark('eps_diluted')}</td>
                    <td className="mono r">
                      {e?.eps_estimate != null && e?.eps_actual != null
                        ? <span className={e.eps_actual >= e.eps_estimate ? 'is-up' : 'is-down'} title={`${e.report_date}`}>{e.eps_actual.toFixed(2)} / {e.eps_estimate.toFixed(2)}</span>
                        : '—'}
                    </td>
                    <td className="mono r">{money(q.fcf, d.currency)}{q.derived.includes('ocf') || q.derived.includes('capex') ? <sup title={t('cf.derived')}>*</sup> : null}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      ) : d.annual.length > 0 ? (
        <div className="table-scroll">
          <p className="cfin__note">{t('cf.annualOnly')}</p>
          <table className="data-table cfin__table">
            <thead><tr><th>{t('cf.year')}</th><th className="r">{t('cf.revenue')}</th><th className="r">{t('cf.op')}</th><th className="r">{t('cf.ni')}</th><th className="r">{t('cf.eps')}</th></tr></thead>
            <tbody>
              {d.annual.map((a) => (
                <tr key={a.end} style={{ cursor: 'default' }}>
                  <td className="mono">{a.end.slice(0, 4)}</td><td className="mono r">{money(a.revenue, d.currency)}</td>
                  <td className="mono r">{money(a.op_income, d.currency)}</td><td className="mono r">{money(a.net_income, d.currency)}</td>
                  <td className="mono r">{a.eps_diluted == null ? '—' : a.eps_diluted.toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : <p className="cfin__note">{t('cf.noNumbers')}</p>}
      {derivedAny && <p className="cfin__note">* {t('cf.derived')}</p>}

      <div className="cfin__docs-head">
        <span className="esched__label">{t('cf.docs')}</span>
        <div className="cfin__toggle">
          {(['earnings', 'all'] as const).map((k) => (
            <button key={k} type="button" className={docs === k ? 'is-on' : ''} onClick={() => setDocs(k)}>{t(`cf.docs.${k}` as never)}</button>
          ))}
        </div>
      </div>
      <ul className="cfin__docs">
        {filings.map((f) => (
          <li key={f.index}>
            <span className="mono cfin__date">{f.filed}</span>
            <span className={`cfin__form is-${f.kind}`}>{f.form}{f.period && f.kind !== 'earnings' ? ` · ${f.period}` : ''}</span>
            <span className="cfin__links">
              {(f.exhibits ?? []).map((e) => (
                <a key={e.url} href={e.url} target="_blank" rel="noreferrer">{exLabel(e, t as never)}{e.pdf ? ' · PDF' : ''} ↗</a>
              ))}
              <a href={f.kind === 'earnings' ? f.index : f.url} target="_blank" rel="noreferrer">
                {f.kind === 'earnings' ? t('cf.filing') : t(`cf.doc.${f.kind}` as never)} ↗
              </a>
            </span>
          </li>
        ))}
      </ul>
      <a className="cfin__all" href={d.browse} target="_blank" rel="noreferrer">{t('cf.allEdgar')} ↗</a>
    </section>
  )
}
