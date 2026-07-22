import { useState, useEffect, useCallback } from 'react'
import { useT } from '../i18n'

type Urow = {
  email: string; name?: string; role?: string; tier?: string; verified?: boolean;
  tg_connected?: boolean; created_at?: string; last_seen?: string; trial_ends_at?: string
}
type Data = {
  total: number; verified: number; telegram_connected: number;
  by_role: { role: string; n: number }[]; users: Urow[]
}

const fmtDate = (s?: string) => {
  if (!s) return '—'
  try { return new Date(s).toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) }
  catch { return '—' }
}

export function AdminPage() {
  const { t } = useT()
  const [token, setToken] = useState<string>(() => localStorage.getItem('sa_admin') || '')
  const [input, setInput] = useState('')
  const [data, setData] = useState<Data | null>(null)
  const [err, setErr] = useState('')
  const [loading, setLoading] = useState(false)

  const load = useCallback(async (tok: string) => {
    if (!tok) return
    setLoading(true); setErr('')
    try {
      const r = await fetch('/api/v1/auth/admin/users', { headers: { 'X-Admin-Token': tok } })
      if (r.status === 401) { setErr('Wrong admin token.'); setData(null); localStorage.removeItem('sa_admin'); setToken(''); return }
      if (!r.ok) { setErr('Failed to load (' + r.status + ').'); return }
      const d = await r.json()
      setData(d)
    } catch {
      setErr('Network error.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { if (token) load(token) }, [token, load])

  const unlock = () => {
    const t = input.trim()
    if (!t) return
    localStorage.setItem('sa_admin', t); setToken(t); setInput('')
  }
  const lock = () => { localStorage.removeItem('sa_admin'); setToken(''); setData(null); setErr('') }

  return (
    <div className="adm-wrap">
      <style>{CSS}</style>

      {!data ? (
        <div className="adm-gate">
          <div className="adm-eyebrow">{t('adm.eyebrow')}</div>
          <h1 className="adm-gate-title">{t('adm.gate.title')}</h1>
          <p className="adm-gate-sub">{t('adm.gate.sub')}</p>
          <input className="adm-input" type="password" placeholder={t('adm.gate.placeholder')} value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') unlock() }} />
          {err && <div className="adm-err">{err}</div>}
          <button className="adm-btn" onClick={unlock} disabled={loading}>
            {loading ? 'Checking…' : 'Unlock'}
          </button>
        </div>
      ) : (
        <div className="adm-dash">
          <div className="adm-head">
            <div>
              <div className="adm-eyebrow">{t('adm.eyebrow')}</div>
              <h1 className="adm-h1">{t('adm.users')}</h1>
            </div>
            <div className="adm-head-actions">
              <button className="adm-ghost" onClick={() => load(token)} disabled={loading}>
                {loading ? '…' : 'Refresh'}
              </button>
              <button className="adm-ghost" onClick={lock}>{t('adm.lock')}</button>
            </div>
          </div>

          <div className="adm-stats">
            <div className="adm-stat">
              <div className="adm-stat-n">{data.total}</div>
              <div className="adm-stat-l">{t('adm.stat.signups')}</div>
            </div>
            <div className="adm-stat">
              <div className="adm-stat-n">{data.verified}</div>
              <div className="adm-stat-l">{t('adm.stat.verified')}</div>
            </div>
            <div className="adm-stat">
              <div className="adm-stat-n adm-cyan">{data.telegram_connected}</div>
              <div className="adm-stat-l">{t('adm.stat.telegram')}</div>
            </div>
          </div>

          {data.by_role?.length > 0 && (
            <div className="adm-roles">
              {data.by_role.map(r => (
                <span key={r.role} className="adm-role-chip">{r.role} <b>{r.n}</b></span>
              ))}
            </div>
          )}

          <div className="adm-table-wrap">
            <table className="adm-table">
              <thead>
                <tr>
                  <th>{t('col.email')}</th><th>{t('col.name')}</th><th>{t('col.role')}</th><th>{t('col.tier')}</th>
                  <th className="adm-c">{t('adm.th.verified')}</th><th className="adm-c">{t('adm.th.tg')}</th>
                  <th className="adm-c">{t('adm.th.joined')}</th><th className="adm-c">{t('adm.th.lastSeen')}</th>
                </tr>
              </thead>
              <tbody>
                {data.users.map(u => (
                  <tr key={u.email}>
                    <td className="adm-mono">{u.email}</td>
                    <td>{u.name || '—'}</td>
                    <td>{u.role || '—'}</td>
                    <td><span className={'adm-tier ' + (u.tier === 'free_trial' ? 'trial' : 'paid')}>{u.tier || '—'}</span></td>
                    <td className="adm-c">{u.verified ? <span className="adm-ok">✓</span> : <span className="adm-dim">—</span>}</td>
                    <td className="adm-c">{u.tg_connected ? <span className="adm-dot" /> : <span className="adm-dim">—</span>}</td>
                    <td className="adm-c adm-dim">{fmtDate(u.created_at)}</td>
                    <td className="adm-c adm-dim">{fmtDate(u.last_seen)}</td>
                  </tr>
                ))}
                {data.users.length === 0 && (
                  <tr><td colSpan={8} className="adm-empty">{t('adm.empty')}</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}

const CSS = `
.adm-wrap{min-height:100vh;background:#05070d;color:#e8edf5;
  font-family:var(--font-sans,Inter,system-ui,sans-serif);
  background-image:radial-gradient(800px 400px at 80% -10%,rgba(56,189,248,.10),transparent 60%),
    radial-gradient(700px 380px at 5% 0%,rgba(167,139,250,.08),transparent 60%);
  padding:48px 24px;display:flex;justify-content:center}
.adm-eyebrow{font-family:var(--font-mono,monospace);font-size:11px;letter-spacing:.28em;
  color:var(--accent-cyan,#38bdf8);text-transform:uppercase;margin-bottom:12px}
.adm-gate{max-width:380px;width:100%;margin-top:14vh;text-align:center;
  background:rgba(17,24,39,.6);border:1px solid rgba(148,163,184,.14);border-radius:18px;padding:38px 32px;
  backdrop-filter:blur(14px)}
.adm-gate-title{font-size:24px;font-weight:700;letter-spacing:-.02em;margin:0 0 8px}
.adm-gate-sub{color:#8a99b0;font-size:14px;line-height:1.55;margin:0 0 22px}
.adm-input{width:100%;font-family:var(--font-mono,monospace);font-size:14px;color:#e8edf5;
  background:#0a0f1c;border:1px solid rgba(148,163,184,.16);border-radius:11px;
  padding:12px 14px;outline:none;margin-bottom:12px}
.adm-input:focus{border-color:var(--accent-cyan,#38bdf8)}
.adm-btn{width:100%;font-weight:600;font-size:14px;color:#06121c;
  background:linear-gradient(120deg,var(--accent-cyan,#38bdf8),#7dd3fc);border:none;border-radius:11px;
  padding:12px;cursor:pointer}
.adm-btn:disabled{opacity:.6;cursor:default}
.adm-err{font-size:12.5px;color:var(--down,#fb7185);margin-bottom:12px}
.adm-dash{max-width:1000px;width:100%}
.adm-head{display:flex;justify-content:space-between;align-items:flex-end;margin-bottom:26px;gap:16px}
.adm-h1{font-size:28px;font-weight:740;letter-spacing:-.02em;margin:0}
.adm-head-actions{display:flex;gap:8px}
.adm-ghost{font-size:13px;color:#cbd5e1;background:rgba(17,24,39,.6);
  border:1px solid rgba(148,163,184,.16);border-radius:10px;padding:8px 16px;cursor:pointer}
.adm-ghost:hover{border-color:rgba(148,163,184,.32)}
.adm-ghost:disabled{opacity:.5;cursor:default}
.adm-stats{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-bottom:18px}
.adm-stat{background:rgba(17,24,39,.55);border:1px solid rgba(148,163,184,.13);border-radius:15px;padding:20px 22px}
.adm-stat-n{font-size:34px;font-weight:760;letter-spacing:-.02em;line-height:1}
.adm-cyan{color:var(--accent-cyan,#38bdf8)}
.adm-stat-l{font-size:12.5px;color:#8a99b0;margin-top:8px}
.adm-roles{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:22px}
.adm-role-chip{font-size:12px;color:#cbd5e1;background:rgba(17,24,39,.5);
  border:1px solid rgba(148,163,184,.13);border-radius:999px;padding:5px 13px}
.adm-role-chip b{color:#e8edf5;margin-left:3px}
.adm-table-wrap{background:rgba(17,24,39,.45);border:1px solid rgba(148,163,184,.12);
  border-radius:15px;overflow:hidden;overflow-x:auto}
.adm-table{width:100%;border-collapse:collapse;font-size:13px;min-width:720px}
.adm-table th{text-align:left;font-size:11px;letter-spacing:.04em;text-transform:uppercase;
  color:#8a99b0;font-weight:600;padding:13px 16px;border-bottom:1px solid rgba(148,163,184,.12);background:rgba(0,0,0,.18)}
.adm-table td{padding:12px 16px;border-bottom:1px solid rgba(148,163,184,.07);color:#cbd5e1}
.adm-table tr:last-child td{border-bottom:none}
.adm-table tr:hover td{background:rgba(56,189,248,.03)}
.adm-c{text-align:center}
.adm-mono{font-family:var(--font-mono,monospace);font-size:12.5px;color:#e8edf5}
.adm-dim{color:#5b6678}
.adm-ok{color:var(--up,#34d399);font-weight:700}
.adm-dot{display:inline-block;width:8px;height:8px;border-radius:50%;
  background:var(--up,#34d399);box-shadow:0 0 8px var(--up,#34d399)}
.adm-tier{font-family:var(--font-mono,monospace);font-size:11px;padding:3px 8px;border-radius:6px}
.adm-tier.trial{color:#fbbf24;background:rgba(251,191,36,.1)}
.adm-tier.paid{color:var(--up,#34d399);background:rgba(52,211,153,.1)}
.adm-empty{text-align:center;color:#5b6678;padding:30px}
@media(max-width:680px){.adm-stats{grid-template-columns:1fr}}
`
