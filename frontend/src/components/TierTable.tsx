import { useHeadline } from '../hooks/useHeadline'
import { useT } from '../i18n'

/**
 * The two calls that hold up, split by company size.
 *
 * Since 2026-10-14 one pooled model covers every US listing over $300M. A skill measured
 * on the old 180 large caps does not carry over to small caps by assumption, so each
 * band is shown against its own base rate. Survivorship bias is larger in small caps
 * (today's listings only), and the note says so.
 */
type BT = { n: number; auc: number; base_rate: number; top_n: number; top_move_rate: number | null; top_z: number | null }
type FT = { n: number; hit: number | null; baseline_hit: number; excess: number | null; t: number | null; verdict: string }

const pc = (v: number | null | undefined) => (v == null ? '—' : `${(v * 100).toFixed(1)}%`)

export function TierTable() {
  const { t } = useT()
  const h = useHeadline() as unknown as { breakout?: { by_tier?: Record<string, BT> }; follow_through?: { by_tier?: Record<string, FT> } } | null
  const bt = h?.breakout?.by_tier ?? {}
  const ft = h?.follow_through?.by_tier ?? {}
  const tiers = (['large', 'mid', 'small'] as const).filter((x) => bt[x] || ft[x])
  if (!tiers.length) return null
  return (
    <section className="card tier-table">
      <h3 className="card-title">{t('tiers.title')}</h3>
      <div className="table-scroll">
        <table className="data-table">
          <thead><tr>
            <th>{t('cal.cap')}</th>
            <th className="r">{t('tiers.b.n')}</th><th className="r">{t('tiers.b.top')}</th><th className="r">{t('tiers.b.base')}</th><th className="r">AUC</th>
            <th className="r">{t('tiers.f.n')}</th><th className="r">{t('tiers.f.hit')}</th><th className="r">{t('tiers.f.base')}</th><th className="r">t</th>
          </tr></thead>
          <tbody>
            {tiers.map((x) => {
              const b = bt[x], f = ft[x]
              const bOk = b?.top_z != null && b.top_z >= 2
              const fOk = f?.t != null && f.t >= 2 && (f.excess ?? 0) > 0
              return (
                <tr key={x} style={{ cursor: 'default' }}>
                  <td><b>{t(`tier.${x}` as 'tier.large')}</b></td>
                  <td className="r mono">{b ? b.n.toLocaleString() : '—'}</td>
                  <td className={`r mono ${bOk ? 'is-up' : ''}`}>{pc(b?.top_move_rate)}</td>
                  <td className="r mono">{pc(b?.base_rate)}</td>
                  <td className="r mono">{b ? b.auc.toFixed(3) : '—'}</td>
                  <td className="r mono">{f ? f.n.toLocaleString() : '—'}</td>
                  <td className={`r mono ${fOk ? 'is-up' : ''}`}>{pc(f?.hit)}</td>
                  <td className="r mono">{pc(f?.baseline_hit)}</td>
                  <td className="r mono">{f?.t != null ? f.t.toFixed(1) : '—'}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <p className="page-note">{t('tiers.note')}</p>
    </section>
  )
}
